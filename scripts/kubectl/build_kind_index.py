#!/usr/bin/env python3
"""One-shot indexer: walks tests/fixtures/kubectl_testcases/ and emits
tests/fixtures/kubectl_testcases/kind_index.json with the shape:

    {"<filename>": {"kinds": ["Pod", "Namespace", ...],
                       "verbs": ["apply", "get", ...],
                       "primary_verb": "get"}}

Signals (highest-confidence first):
  1. YAML manifest literals inside the file: `kind: <Kind>` (case-sensitive)
  2. `k8s_client.<method>()` names: list_namespaced_pod -> Pod,
     list_namespace -> Namespace, read_namespaced_service_account -> ServiceAccount, etc.
  3. `cli("verb", "resource", ...)` and `kubectl_bin([...])` argv where
     resource matches a known singular/plural/alias -> mapped kind
  4. Verb comes from filename OR from cli/kubectl_bin argv when workflow

Design choices:
  * Regex + string scan only (no Python-AST parse to keep it cheap for 5k files)
  * Deterministic sorted output for stable diffs
  * Filenames are the JSON keys so downstream code_paths can O(1) lookup
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_ALL_KINDS = frozenset({
    "Pod",
    "Service",
    "Deployment",
    "ReplicaSet",
    "StatefulSet",
    "DaemonSet",
    "Job",
    "CronJob",
    "ConfigMap",
    "Secret",
    "Namespace",
    "Ingress",
    "PersistentVolumeClaim",
    "ServiceAccount",
})

_RESOURCE_TO_KIND: dict[str, str] = {}
_RES_ALIASES: dict[str, tuple[str, ...]] = {
    "Pod": ("pod", "pods", "po"),
    "Service": ("service", "services", "svc"),
    "Deployment": ("deployment", "deployments", "deploy"),
    "ReplicaSet": ("replicaset", "replicasets", "rs"),
    "StatefulSet": ("statefulset", "statefulsets", "sts"),
    "DaemonSet": ("daemonset", "daemonsets", "ds"),
    "Job": ("job", "jobs"),
    "CronJob": ("cronjob", "cronjobs", "cj"),
    "ConfigMap": ("configmap", "configmaps", "cm"),
    "Secret": ("secret", "secrets"),
    "Namespace": ("namespace", "namespaces", "ns"),
    "Ingress": ("ingress", "ingresses", "ing"),
    "PersistentVolumeClaim": (
        "persistentvolumeclaim",
        "persistentvolumeclaims",
        "pvc",
    ),
    "ServiceAccount": (
        "serviceaccount",
        "serviceaccounts",
        "sa",
    ),
}
for _kind, _aliases in _RES_ALIASES.items():
    for _alias in _aliases:
        _RESOURCE_TO_KIND[_alias] = _kind

_METHOD_SUFFIX_TO_KIND: dict[str, str] = {
    "pod": "Pod",
    "pods": "Pod",
    "service": "Service",
    "services": "Service",
    "deployment": "Deployment",
    "deployments": "Deployment",
    "replica_set": "ReplicaSet",
    "stateful_set": "StatefulSet",
    "daemon_set": "DaemonSet",
    "job": "Job",
    "cron_job": "CronJob",
    "config_map": "ConfigMap",
    "secret": "Secret",
    "namespace": "Namespace",
    "ingress": "Ingress",
    "persistent_volume_claim": "PersistentVolumeClaim",
    "service_account": "ServiceAccount",
}

_KNOWN_VERBS = frozenset({
    "apply",
    "create",
    "delete",
    "describe",
    "get",
    "label",
    "patch",
    "scale",
})

_YAML_KIND_RE = re.compile(r"\bkind:\s*([A-Z][A-Za-z0-9]+)")
# cli("verb", "resource", ...) OR cli('verb', 'resource', ...)
_CLI_CALL_RE = re.compile(
    r"""cli\(\s*["']([a-z][a-z0-9-]*)["']\s*,\s*["']([a-z][a-z0-9-]*)["']"""
)
# kubectl_bin(["verb", "resource", ...]) OR kubectl_bin(['verb', 'resource', ...])
_BIN_CALL_RE = re.compile(
    r"""kubectl_bin\(\s*\[\s*["']([a-z][a-z0-9-]*)["']\s*,\s*["']([a-z][a-z0-9-]*)["']"""
)
# cli("verb", ...) with just verb (for namespace create style)
_CLI_VERB_ONLY_RE = re.compile(r"""cli\(\s*["']([a-z][a-z0-9-]*)["']""")
_BIN_VERB_ONLY_RE = re.compile(r"""kubectl_bin\(\s*\[\s*["']([a-z][a-z0-9-]*)["']""")
# k8s_client.foo.bar_verb_kind_name(   or  k8s_client.method(
# Also matches AppsV1Api(...).read_namespaced_deployment(name=...)
_K8S_METHOD_RE = re.compile(
    r"\.(list|list_namespaced|read|read_namespaced|create|create_namespaced|"
    r"delete|delete_namespaced|patch|patch_namespaced|replace|replace_namespaced)"
    r"_([a-z_]+?)\("
)
# Fallback: bare k8s_client.list_namespace(...) etc. captures 'namespace' without _namespaced_ prefix
_K8S_BARE_METHOD_RE = re.compile(r"\.(list|read|create|delete|patch|replace)_([a-z_]+?)\(")

# Filename encodes the verb: test_kubectl_<verb>_<beh>_<NN>.py
_FILENAME_VERB_RE = re.compile(r"^test_kubectl_([a-z]+)_")


def detect_kinds_and_verbs(body: str, filename: str) -> tuple[set[str], set[str], str]:
    kinds: set[str] = set()
    verbs: set[str] = set()

    for match in _YAML_KIND_RE.finditer(body):
        candidate = match.group(1)
        if candidate in _ALL_KINDS:
            kinds.add(candidate)

    for verb, resource in _CLI_CALL_RE.findall(body):
        if verb in _KNOWN_VERBS:
            verbs.add(verb)
        mapped = _RESOURCE_TO_KIND.get(resource)
        if mapped is not None:
            kinds.add(mapped)

    for verb, resource in _BIN_CALL_RE.findall(body):
        if verb in _KNOWN_VERBS:
            verbs.add(verb)
        mapped = _RESOURCE_TO_KIND.get(resource)
        if mapped is not None:
            kinds.add(mapped)

    for verb in _CLI_VERB_ONLY_RE.findall(body):
        if verb in _KNOWN_VERBS:
            verbs.add(verb)
    for verb in _BIN_VERB_ONLY_RE.findall(body):
        if verb in _KNOWN_VERBS:
            verbs.add(verb)

    for _method, tail in _K8S_METHOD_RE.findall(body):
        mapped = _METHOD_SUFFIX_TO_KIND.get(tail)
        if mapped is not None:
            kinds.add(mapped)
    for _method, tail in _K8S_BARE_METHOD_RE.findall(body):
        mapped = _METHOD_SUFFIX_TO_KIND.get(tail)
        if mapped is not None:
            kinds.add(mapped)

    primary_verb = ""
    fname_match = _FILENAME_VERB_RE.match(filename)
    if fname_match is not None:
        primary_verb = fname_match.group(1)
    return kinds, verbs, primary_verb


def main() -> int:
    fixture_dir = Path(
        "/Users/anshkataria/Desktop/23-july/Repo2RLEnv/tests/fixtures/kubectl_testcases"
    )
    if not fixture_dir.is_dir():
        print(f"ERROR: fixture dir not found: {fixture_dir}", file=sys.stderr)
        return 1

    index: dict[str, dict[str, object]] = {}
    total = 0
    no_kinds = 0
    kind_totals: dict[str, int] = {k: 0 for k in _ALL_KINDS}
    verb_totals: dict[str, int] = {v: 0 for v in _KNOWN_VERBS}
    verb_totals["workflow"] = 0

    for path in sorted(fixture_dir.glob("test_kubectl_*.py")):
        total += 1
        body = path.read_text(encoding="utf-8", errors="replace")
        kinds, verbs, primary_verb = detect_kinds_and_verbs(body, path.name)
        if not kinds:
            no_kinds += 1
        index[path.name] = {
            "kinds": sorted(kinds),
            "verbs": sorted(verbs),
            "primary_verb": primary_verb,
        }
        for k in kinds:
            kind_totals[k] = kind_totals.get(k, 0) + 1
        for v in verbs:
            verb_totals[v] = verb_totals.get(v, 0) + 1
        if primary_verb == "workflow":
            verb_totals["workflow"] += 1

    out_path = fixture_dir / "kind_index.json"
    out_path.write_text(
        json.dumps(index, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )

    # Report to stderr for CI capture
    print(f"total_files={total}", file=sys.stderr)
    print(f"files_with_zero_kinds={no_kinds}", file=sys.stderr)
    print("kind_totals=" + json.dumps(dict(sorted(kind_totals.items()))), file=sys.stderr)
    print("verb_totals=" + json.dumps(dict(sorted(verb_totals.items()))), file=sys.stderr)
    print(f"wrote={out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
