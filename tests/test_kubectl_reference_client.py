"""C9 gate: reference kubectl client + per-task AST pruner."""

from __future__ import annotations

import ast
import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from repo2rlenv.pipelines._cli_app_backends.simulation import _reference_kubectl_client as _ref
from repo2rlenv.pipelines._cli_app_backends.simulation.kwok import (
    KwokSimulationBackend,
)

_CLIENT_PATH = Path(_ref.__file__)
_CLIENT_SRC = _CLIENT_PATH.read_text(encoding="utf-8")


def test_full_client_parses_via_ast():
    tree = ast.parse(_CLIENT_SRC)
    assert isinstance(tree, ast.Module)


def test_all_eight_public_methods_present():
    tree = ast.parse(_CLIENT_SRC)
    kubectl_client = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "KubectlClient"
    )
    method_names = {
        m.name
        for m in kubectl_client.body
        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    required = {"get", "list", "create", "apply", "delete", "patch", "scale", "describe"}
    missing = required - method_names
    assert not missing, f"KubectlClient missing public methods: {sorted(missing)}"


def test_strip_logic_present_and_names_both_volatile_keys():
    assert "resourceVersion" in _CLIENT_SRC, "reference client must mention resourceVersion"
    assert "creationTimestamp" in _CLIENT_SRC, "reference client must mention creationTimestamp"
    assert "_STRIP_META_KEYS" in _CLIENT_SRC, "must expose a strip constant for AST-level pinning"
    assert "def _strip_volatile" in _CLIENT_SRC, "must define the volatile-strip helper"


def test_strip_volatile_removes_both_keys_recursively():
    payload = {
        "kind": "Pod",
        "metadata": {
            "name": "foo",
            "resourceVersion": "12345",
            "creationTimestamp": "2026-07-15T00:00:00Z",
        },
        "items": [
            {"metadata": {"resourceVersion": "1", "creationTimestamp": "x", "name": "a"}},
        ],
    }
    cleaned = _ref._strip_volatile(payload)
    assert "resourceVersion" not in cleaned["metadata"]
    assert "creationTimestamp" not in cleaned["metadata"]
    assert cleaned["metadata"]["name"] == "foo"
    assert "resourceVersion" not in cleaned["items"][0]["metadata"]
    assert "creationTimestamp" not in cleaned["items"][0]["metadata"]
    assert cleaned["items"][0]["metadata"]["name"] == "a"


def test_uses_stdlib_only_no_kubernetes_import():
    tree = ast.parse(_CLIENT_SRC)
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    for imp in imports:
        head = imp.split(".", 1)[0]
        assert head != "kubernetes", f"reference client must not import kubernetes: found {imp!r}"


def _make_mock_response(payload: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.__enter__ = lambda self=resp: resp
    resp.__exit__ = lambda self, *a: False
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.status = status
    return resp


def test_get_makes_correct_http_call():
    client = _ref.KubectlClient(apiserver="http://127.0.0.1:9999")
    payload = {"kind": "Pod", "metadata": {"name": "foo", "namespace": "default"}}
    with patch("urllib.request.urlopen", return_value=_make_mock_response(payload)) as mock_open:
        result = client.get("pods", name="foo", namespace="default")
    assert result["kind"] == "Pod"
    request = mock_open.call_args[0][0]
    assert request.get_method() == "GET"
    assert "api/v1/namespaces/default/pods/foo" in request.full_url


def test_list_uses_no_name_returns_items():
    client = _ref.KubectlClient(apiserver="http://127.0.0.1:9999")
    payload = {"items": [{"metadata": {"name": "p1"}}, {"metadata": {"name": "p2"}}]}
    with patch("urllib.request.urlopen", return_value=_make_mock_response(payload)):
        result = client.list("pods", namespace="default")
    assert isinstance(result, list) and len(result) == 2


def test_create_uses_post():
    client = _ref.KubectlClient(apiserver="http://127.0.0.1:9999")
    manifest = {"kind": "ConfigMap", "metadata": {"name": "cm", "namespace": "default"}}
    with patch("urllib.request.urlopen", return_value=_make_mock_response(manifest)) as mock_open:
        client.create(manifest)
    request = mock_open.call_args[0][0]
    assert request.get_method() == "POST"


def test_delete_uses_delete_verb():
    client = _ref.KubectlClient(apiserver="http://127.0.0.1:9999")
    with patch("urllib.request.urlopen", return_value=_make_mock_response({})) as mock_open:
        client.delete("pods", name="foo", namespace="default")
    request = mock_open.call_args[0][0]
    assert request.get_method() == "DELETE"


def test_apply_falls_back_to_post_when_get_404s():
    client = _ref.KubectlClient(apiserver="http://127.0.0.1:9999")
    manifest = {"kind": "Pod", "metadata": {"name": "new", "namespace": "default"}}
    calls: list[str] = []

    def fake_urlopen(req, *a, **kw):
        calls.append(req.get_method())
        if req.get_method() == "GET":
            body = json.dumps({"reason": "NotFound"}).encode("utf-8")
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(body))
        return _make_mock_response(manifest)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        client.apply(manifest)
    assert calls == ["GET", "POST"]


def test_scale_targets_scale_subresource():
    client = _ref.KubectlClient(apiserver="http://127.0.0.1:9999")
    with patch("urllib.request.urlopen", return_value=_make_mock_response({})) as mock_open:
        client.scale("deployments", "app", replicas=3, namespace="default")
    request = mock_open.call_args[0][0]
    assert "/deployments/app/scale" in request.full_url
    assert request.get_method() == "PATCH"


def test_response_strips_resource_version_and_timestamp():
    client = _ref.KubectlClient(apiserver="http://127.0.0.1:9999")
    payload = {
        "metadata": {
            "name": "foo",
            "resourceVersion": "999",
            "creationTimestamp": "2026-07-15T00:00:00Z",
        }
    }
    with patch("urllib.request.urlopen", return_value=_make_mock_response(payload)):
        result = client.get("pods", name="foo", namespace="default")
    assert "resourceVersion" not in result["metadata"]
    assert "creationTimestamp" not in result["metadata"]
    assert result["metadata"]["name"] == "foo"


class _TaskSpec:
    def __init__(self, commands: list[str], kinds: list[str]) -> None:
        self.commands = commands
        self.kinds = kinds


def test_prune_only_pods_configmaps_get_apply_delete():
    task = _TaskSpec(commands=["get", "apply", "delete"], kinds=["pods", "configmaps"])
    pruned = KwokSimulationBackend.emit_reference_client(task)

    tree = ast.parse(pruned)
    client_cls = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "KubectlClient"
    )
    method_names = {
        m.name for m in client_cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "get" in method_names
    assert "apply" in method_names
    assert "delete" in method_names
    assert "list" in method_names
    assert "scale" not in method_names, "scale must be pruned when task doesn't need it"
    assert "patch" not in method_names, "patch must be pruned when task doesn't need it"

    assert "'pods'" in pruned or '"pods"' in pruned
    assert "'configmaps'" in pruned or '"configmaps"' in pruned
    assert "'deployments':" not in pruned and '"deployments":' not in pruned


def test_prune_falls_back_to_full_when_no_task_spec():
    src = KwokSimulationBackend.emit_reference_client(None)
    assert "def scale" in src
    assert "def patch" in src
    assert "def describe" in src


def test_prune_falls_back_to_full_when_task_spec_missing_attrs():
    class Empty:
        pass

    src = KwokSimulationBackend.emit_reference_client(Empty())
    assert "def scale" in src
    assert "def patch" in src


def test_emit_reference_client_output_is_valid_python():
    task = _TaskSpec(commands=["get"], kinds=["pods"])
    pruned = KwokSimulationBackend.emit_reference_client(task)
    ast.parse(pruned)


def test_kubectl_client_reads_apiserver_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KUBECTL_APISERVER", "http://kwok.test:1234")
    client = _ref.KubectlClient()
    assert client.apiserver == "http://kwok.test:1234"


def test_api_error_carries_status_and_reason():
    client = _ref.KubectlClient(apiserver="http://127.0.0.1:9999")

    def fake_urlopen(req, *a, **kw):
        body = json.dumps({"reason": "NotFound", "message": "missing"}).encode("utf-8")
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(body))

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        with pytest.raises(_ref.ApiError) as excinfo:
            client.get("pods", name="missing", namespace="default")
    assert excinfo.value.status == 404
    assert excinfo.value.reason == "NotFound"
