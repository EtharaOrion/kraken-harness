"""Reference kubectl client — stdlib-only raw-REST talker for kwok's apiserver.

C9 discriminative floor. An agent submission must at minimum produce
equivalent behaviour to satisfy the LLM-synthesized test suite; this
module is the ground-truth reference client that the pipeline may either
ship verbatim (for the golden slice) or prune per-task before emission.

Design notes:

* stdlib-only (urllib.request + json + time). Deliberately does NOT import
  the `kubernetes` Python package to avoid drift against a version that the
  emitted task's Docker image is pinned on. The emitted task DOES install
  `kubernetes==31.0.0` for the test-side `k8s_client` fixture, but this
  reference client sends raw REST so the wire shape is inspectable.

* Configuration by env: KUBECTL_APISERVER (default http://127.0.0.1:8080) —
  set by the conftest to the kwok cluster's random loopback port. No TLS
  path is exercised (kwok defaults to unauth HTTP for in-cluster tests).

* `resourceVersion` and `creationTimestamp` are stripped from every response
  BEFORE returning to callers. Oracle-explicit invariant: two invocations
  of the client against the same cluster state MUST produce byte-comparable
  return dicts — kwok stamps a monotonic resourceVersion on every response
  and generates timestamps on-the-fly, so leaving them in would break
  byte-comparison in workflow-test snapshotting.

Public surface (stable):

    get(kind, name=None, namespace=None) -> dict | list
    list(kind, namespace=None, label_selector=None) -> list
    create(manifest) -> dict
    apply(manifest) -> dict                # idempotent create-or-update
    delete(kind, name, namespace=None) -> dict
    patch(kind, name, patch, namespace=None, patch_type="strategic") -> dict
    scale(kind, name, replicas, namespace=None) -> dict
    describe(kind, name, namespace=None) -> str

Kind catalog:

    KINDS maps lowercased pluralised kubectl kinds (pods, deployments, ...)
    to (api_group_path, resource_plural, namespaced) tuples. Extending the
    catalog is the single-point-of-entry for supporting a new kind.

License: Apache-2.0. Released under the Repo2RLEnv license umbrella.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_APISERVER = "http://127.0.0.1:8080"

# Kind catalog. Values: (api_group_path, plural, namespaced).
# The api_group_path is the URL fragment BEFORE /namespaces/<ns>/<plural>.
# For core v1 kinds: "api/v1". For grouped kinds: "apis/<group>/<version>".
KINDS: dict[str, tuple[str, str, bool]] = {
    "pods": ("api/v1", "pods", True),
    "pod": ("api/v1", "pods", True),
    "services": ("api/v1", "services", True),
    "service": ("api/v1", "services", True),
    "svc": ("api/v1", "services", True),
    "configmaps": ("api/v1", "configmaps", True),
    "configmap": ("api/v1", "configmaps", True),
    "cm": ("api/v1", "configmaps", True),
    "secrets": ("api/v1", "secrets", True),
    "secret": ("api/v1", "secrets", True),
    "namespaces": ("api/v1", "namespaces", False),
    "namespace": ("api/v1", "namespaces", False),
    "ns": ("api/v1", "namespaces", False),
    "nodes": ("api/v1", "nodes", False),
    "node": ("api/v1", "nodes", False),
    "no": ("api/v1", "nodes", False),
    "persistentvolumes": ("api/v1", "persistentvolumes", False),
    "persistentvolumeclaims": ("api/v1", "persistentvolumeclaims", True),
    "serviceaccounts": ("api/v1", "serviceaccounts", True),
    "deployments": ("apis/apps/v1", "deployments", True),
    "deployment": ("apis/apps/v1", "deployments", True),
    "deploy": ("apis/apps/v1", "deployments", True),
    "statefulsets": ("apis/apps/v1", "statefulsets", True),
    "statefulset": ("apis/apps/v1", "statefulsets", True),
    "daemonsets": ("apis/apps/v1", "daemonsets", True),
    "daemonset": ("apis/apps/v1", "daemonsets", True),
    "replicasets": ("apis/apps/v1", "replicasets", True),
    "jobs": ("apis/batch/v1", "jobs", True),
    "cronjobs": ("apis/batch/v1", "cronjobs", True),
    "ingresses": ("apis/networking.k8s.io/v1", "ingresses", True),
    "networkpolicies": ("apis/networking.k8s.io/v1", "networkpolicies", True),
}

# Keys stripped from every returned dict before handing back to callers.
# resourceVersion: monotonic — perturbs byte-comparability across test runs.
# creationTimestamp: wall-clock — perturbs byte-comparability.
_STRIP_META_KEYS = ("resourceVersion", "creationTimestamp")


def _strip_volatile(obj: Any) -> Any:
    """Recursively remove volatile metadata fields.

    Oracle-explicit: `resourceVersion` and `creationTimestamp` MUST be
    stripped from all responses before returning so results are byte-
    comparable across test runs.
    """
    if isinstance(obj, dict):
        cleaned = {k: _strip_volatile(v) for k, v in obj.items() if k not in _STRIP_META_KEYS}
        return cleaned
    if isinstance(obj, list):
        return [_strip_volatile(x) for x in obj]
    return obj


def _resolve_kind(kind: str) -> tuple[str, str, bool]:
    key = kind.lower().rstrip(".")
    if key not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; supported: {sorted(set(KINDS))}")
    return KINDS[key]


def _resource_path(kind: str, name: str | None, namespace: str | None) -> str:
    api_path, plural, namespaced = _resolve_kind(kind)
    if namespaced:
        ns = namespace or "default"
        base = f"{api_path}/namespaces/{ns}/{plural}"
    else:
        base = f"{api_path}/{plural}"
    if name:
        return f"{base}/{name}"
    return base


class ApiError(RuntimeError):
    """Wraps a kubectl-style apiserver error with .status and .reason."""

    def __init__(self, status: int, reason: str, body: str = "") -> None:
        super().__init__(f"{status} {reason}: {body[:200]}")
        self.status = status
        self.reason = reason
        self.body = body


class KubectlClient:
    """Raw-REST kubectl client speaking to kwok's apiserver.

    Configure via env KUBECTL_APISERVER or the constructor. All responses
    have `resourceVersion` and `creationTimestamp` stripped.
    """

    def __init__(self, apiserver: str | None = None, timeout: float = 10.0) -> None:
        import os

        self.apiserver = (
            apiserver or os.environ.get("KUBECTL_APISERVER", DEFAULT_APISERVER)
        ).rstrip("/")
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        query: dict | None = None,
        content_type: str = "application/json",
    ) -> dict:
        url = f"{self.apiserver}/{path.lstrip('/')}"
        if query:
            url = (
                url
                + "?"
                + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
            )
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            reason = _parse_status_reason(body_text) or exc.reason or "Unknown"
            raise ApiError(exc.code, reason, body_text) from None
        parsed = json.loads(raw) if raw else {}
        return _strip_volatile(parsed)

    def get(self, kind: str, name: str | None = None, namespace: str | None = None) -> dict | list:
        """Fetch one object (when name given) or list objects (no name)."""
        if name is None:
            return self.list(kind, namespace=namespace)
        path = _resource_path(kind, name, namespace)
        return self._request("GET", path)

    def list(
        self,
        kind: str,
        namespace: str | None = None,
        label_selector: str | None = None,
    ) -> list:
        """List objects of a kind, optionally scoped by namespace + selector."""
        path = _resource_path(kind, None, namespace)
        query = {"labelSelector": label_selector} if label_selector else None
        payload = self._request("GET", path, query=query)
        items = payload.get("items", []) if isinstance(payload, dict) else []
        return items

    def create(self, manifest: dict) -> dict:
        """POST a manifest; raises ApiError on non-2xx (including AlreadyExists)."""
        kind = manifest.get("kind", "")
        namespace = manifest.get("metadata", {}).get("namespace")
        path = _resource_path(kind, None, namespace)
        return self._request("POST", path, body=manifest)

    def apply(self, manifest: dict) -> dict:
        """Idempotent create-or-update: try GET; PUT if present, POST otherwise."""
        kind = manifest.get("kind", "")
        name = manifest.get("metadata", {}).get("name")
        namespace = manifest.get("metadata", {}).get("namespace")
        if not name:
            raise ValueError("apply(): manifest must include metadata.name")
        try:
            existing = self.get(kind, name, namespace)
            if isinstance(existing, dict):
                path = _resource_path(kind, name, namespace)
                return self._request("PUT", path, body=manifest)
        except ApiError as exc:
            if exc.status != 404:
                raise
        return self.create(manifest)

    def delete(self, kind: str, name: str, namespace: str | None = None) -> dict:
        """DELETE one object; raises ApiError(404) if absent."""
        path = _resource_path(kind, name, namespace)
        return self._request("DELETE", path)

    def patch(
        self,
        kind: str,
        name: str,
        patch: dict,
        namespace: str | None = None,
        patch_type: str = "strategic",
    ) -> dict:
        """PATCH with Content-Type per patch_type (strategic/merge/json)."""
        content_type = {
            "strategic": "application/strategic-merge-patch+json",
            "merge": "application/merge-patch+json",
            "json": "application/json-patch+json",
        }.get(patch_type, "application/strategic-merge-patch+json")
        path = _resource_path(kind, name, namespace)
        return self._request("PATCH", path, body=patch, content_type=content_type)

    def scale(self, kind: str, name: str, replicas: int, namespace: str | None = None) -> dict:
        """Set spec.replicas via PATCH on the scale subresource."""
        api_path, plural, namespaced = _resolve_kind(kind)
        if namespaced:
            ns = namespace or "default"
            path = f"{api_path}/namespaces/{ns}/{plural}/{name}/scale"
        else:
            path = f"{api_path}/{plural}/{name}/scale"
        body = {"spec": {"replicas": int(replicas)}}
        return self._request("PATCH", path, body=body, content_type="application/merge-patch+json")

    def describe(self, kind: str, name: str, namespace: str | None = None) -> str:
        """Format a kubectl-style describe block from a fetched object."""
        obj = self.get(kind, name, namespace)
        if not isinstance(obj, dict):
            raise ApiError(404, "NotFound", f"describe: {kind}/{name} not found")
        meta = obj.get("metadata", {}) or {}
        spec = obj.get("spec", {}) or {}
        status = obj.get("status", {}) or {}
        lines = [
            f"Name:         {meta.get('name', '')}",
            f"Namespace:    {meta.get('namespace', '')}",
            f"Labels:       {_format_map(meta.get('labels', {}))}",
            f"Annotations:  {_format_map(meta.get('annotations', {}))}",
            f"Kind:         {obj.get('kind', kind)}",
        ]
        if spec:
            replicas = spec.get("replicas")
            if replicas is not None:
                lines.append(f"Replicas:     {replicas}")
        if status:
            phase = status.get("phase")
            if phase:
                lines.append(f"Status:       {phase}")
        return "\n".join(lines) + "\n"


def _format_map(m: dict) -> str:
    if not m:
        return "<none>"
    return ",".join(f"{k}={v}" for k, v in sorted(m.items()))


def _parse_status_reason(body: str) -> str | None:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(payload, dict):
        reason = payload.get("reason")
        if isinstance(reason, str):
            return reason
    return None


def wait_for_apiserver(apiserver: str = DEFAULT_APISERVER, timeout: float = 15.0) -> None:
    """Block until the apiserver's /readyz returns 200 or timeout expires."""
    deadline = time.time() + timeout
    url = f"{apiserver.rstrip('/')}/readyz"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            pass
        time.sleep(0.1)
    raise RuntimeError(f"apiserver not ready within {timeout}s at {apiserver}")
