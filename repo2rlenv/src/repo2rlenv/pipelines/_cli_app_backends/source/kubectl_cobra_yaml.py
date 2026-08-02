"""KubectlCobraYamlSource — host-side loader for the cobra-doc YAML bundle.

The Go extractor at ``cobra_extractor/main.go`` runs inside the bootstrap
sandbox and emits a YAML tree via ``cobra/doc.GenYamlTree``. A bundling
step (bootstrap-time) concatenates that tree into a single file at
``envs/<owner>_<repo>/kubectl_spec.yaml`` shaped like::

    metadata:
      kubectl_version: "v1.31.0"
      extractor_version: "0.1.0"
      git_sha: "<40-hex>"
    commands:
      - name: get
        synopsis: "Display one or many resources"
        description: "..."
        usage: "kubectl get ..."
        example: "kubectl get pods"
        flags:
          - {name: output, shorthand: o, type: string, default: "", usage: "..."}

This module parses that bundle into ``CliSpec`` + ``CommandSpec`` objects
and synthesises per-command ``TestIntent`` templates. The three templates
per command (``happy_path``, ``error_nonexistent``, ``error_invalid_args``)
are shape-only seeds — LLM synthesis downstream (C5) fills in realistic
resource names and expected assertions.

Released under Apache-2.0.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any, ClassVar

import yaml

from repo2rlenv.pipelines import _cli_app_extract as _E
from repo2rlenv.pipelines._cli_app_backends.source.base import (
    CommandSourceBackend,
    register_source,
)

_DEFAULT_BUNDLE_NAME = "kubectl_spec.yaml"


_VERB_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "get": [
        {"kind": "list_default", "tail": ["pods"], "exit": 0, "tag": "happy_path"},
        {"kind": "list_n_short", "tail": ["pods", "-n", "default"], "exit": 0, "tag": "happy_path"},
        {
            "kind": "list_namespace_long",
            "tail": ["pods", "--namespace", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {"kind": "list_json", "tail": ["pods", "-o", "json"], "exit": 0, "tag": "happy_path"},
        {"kind": "list_yaml", "tail": ["pods", "-o", "yaml"], "exit": 0, "tag": "happy_path"},
        {
            "kind": "list_json_ns",
            "tail": ["pods", "-o", "json", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "get_by_name",
            "tail": ["pod", "<resource>", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "get_by_name_json",
            "tail": ["pod", "<resource>", "-o", "json", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "get_by_name_yaml",
            "tail": ["pod", "<resource>", "-o", "yaml", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "list_deployments",
            "tail": ["deployments", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "list_services",
            "tail": ["services", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "list_configmaps",
            "tail": ["configmaps", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "get_pod_missing",
            "tail": ["pod", "<nonexistent>", "-n", "default"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "get_deployment_missing",
            "tail": ["deployment", "<nonexistent>", "-n", "default"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "get_configmap_missing",
            "tail": ["configmap", "<nonexistent>", "-n", "default"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "invalid_flag",
            "tail": ["pods", "--invalid-flag"],
            "exit": 2,
            "tag": "error_invalid_args",
        },
        {"kind": "no_args", "tail": [], "exit": 1, "tag": "error_invalid_args"},
        {
            "kind": "only_ns_no_positional",
            "tail": ["--namespace", "default"],
            "exit": 1,
            "tag": "error_invalid_args",
        },
        {"kind": "list_namespaces", "tail": ["namespaces"], "exit": 0, "tag": "happy_path"},
        {
            "kind": "list_kube_system",
            "tail": ["pods", "-n", "kube-system"],
            "exit": 0,
            "tag": "happy_path",
        },
    ],
    "apply": [
        {"kind": "apply_pod", "tail": ["-f", "<pod-manifest>"], "exit": 0, "tag": "happy_path"},
        {
            "kind": "apply_pod_n",
            "tail": ["-f", "<pod-manifest>", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "apply_pod_namespace_long",
            "tail": ["-f", "<pod-manifest>", "--namespace", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "apply_deployment",
            "tail": ["-f", "<deployment-manifest>"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "apply_deployment_n",
            "tail": ["-f", "<deployment-manifest>", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "apply_configmap",
            "tail": ["-f", "<configmap-manifest>"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "apply_configmap_n",
            "tail": ["-f", "<configmap-manifest>", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "apply_service",
            "tail": ["-f", "<service-manifest>"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "apply_service_n",
            "tail": ["-f", "<service-manifest>", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "apply_namespace",
            "tail": ["-f", "<namespace-manifest>"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "apply_filename_long",
            "tail": ["--filename", "<pod-manifest>"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "apply_pod_kube_system",
            "tail": ["-f", "<pod-manifest>", "-n", "kube-system"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "apply_deployment_test_ns",
            "tail": ["-f", "<deployment-manifest>", "-n", "test-ns"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "missing_file",
            "tail": ["-f", "<nonexistent>.yaml"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "missing_file_n",
            "tail": ["-f", "<nonexistent>.yaml", "-n", "default"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "missing_file_yml",
            "tail": ["-f", "<nonexistent>.yml"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "missing_file_long",
            "tail": ["--filename", "<nonexistent>.yaml"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "invalid_flag",
            "tail": ["--invalid-flag"],
            "exit": 2,
            "tag": "error_invalid_args",
        },
        {"kind": "no_args", "tail": [], "exit": 1, "tag": "error_invalid_args"},
        {
            "kind": "extra_bad_flag",
            "tail": ["-f", "<pod-manifest>", "--invalid-flag"],
            "exit": 2,
            "tag": "error_invalid_args",
        },
    ],
    "delete": [
        {
            "kind": "delete_pod",
            "tail": ["pod", "<resource>", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "delete_pod_namespace_long",
            "tail": ["pod", "<resource>", "--namespace", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "delete_deployment",
            "tail": ["deployment", "<resource>", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "delete_service",
            "tail": ["service", "<resource>", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "delete_configmap",
            "tail": ["configmap", "<resource>", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "delete_namespace",
            "tail": ["namespace", "<resource>"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "delete_pod_force",
            "tail": ["pod", "<resource>", "--force", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "delete_pod_grace_0",
            "tail": ["pod", "<resource>", "--grace-period", "0", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "delete_pod_grace_30",
            "tail": ["pod", "<resource>", "--grace-period", "30", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "delete_pod_force_grace",
            "tail": ["pod", "<resource>", "--force", "--grace-period", "0", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "delete_pod_kube_system",
            "tail": ["pod", "<resource>", "-n", "kube-system"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "delete_deployment_kube_system",
            "tail": ["deployment", "<resource>", "-n", "kube-system"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "delete_pod_missing",
            "tail": ["pod", "<nonexistent>", "-n", "default"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "delete_deployment_missing",
            "tail": ["deployment", "<nonexistent>", "-n", "default"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "delete_namespace_missing",
            "tail": ["namespace", "<nonexistent>"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "delete_configmap_missing",
            "tail": ["configmap", "<nonexistent>", "-n", "default"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "delete_invalid_flag",
            "tail": ["pod", "<resource>", "--invalid-flag", "-n", "default"],
            "exit": 2,
            "tag": "error_invalid_args",
        },
        {"kind": "delete_no_args", "tail": [], "exit": 1, "tag": "error_invalid_args"},
        {"kind": "delete_only_kind", "tail": ["pod"], "exit": 1, "tag": "error_invalid_args"},
        {
            "kind": "delete_unknown_kind",
            "tail": ["invalidkind", "<resource>", "-n", "default"],
            "exit": 1,
            "tag": "error_invalid_args",
        },
    ],
    "create": [
        {"kind": "create_pod_f", "tail": ["-f", "<pod-manifest>"], "exit": 0, "tag": "happy_path"},
        {
            "kind": "create_pod_f_n",
            "tail": ["-f", "<pod-manifest>", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "create_deployment_f",
            "tail": ["-f", "<deployment-manifest>"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "create_deployment_f_n",
            "tail": ["-f", "<deployment-manifest>", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "create_namespace_f",
            "tail": ["-f", "<namespace-manifest>"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "create_pod_filename_long",
            "tail": ["--filename", "<pod-manifest>"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "create_pod_filename_long_n",
            "tail": ["--filename", "<pod-manifest>", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "create_pod_namespace_long",
            "tail": ["-f", "<pod-manifest>", "--namespace", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "create_pod_test_ns",
            "tail": ["-f", "<pod-manifest>", "-n", "test-ns"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "create_deployment_kube_system",
            "tail": ["-f", "<deployment-manifest>", "-n", "kube-system"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "create_namespace_bare",
            "tail": ["namespace", "<resource>"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "create_namespace_bare2",
            "tail": ["namespace", "<resource-2>"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "create_missing_file",
            "tail": ["-f", "<nonexistent>.yaml"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "create_missing_file_n",
            "tail": ["-f", "<nonexistent>.yaml", "-n", "default"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "create_missing_file_long",
            "tail": ["--filename", "<nonexistent>.yaml"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "create_missing_file_yml",
            "tail": ["-f", "<nonexistent>.yml"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "create_invalid_flag",
            "tail": ["--invalid-flag"],
            "exit": 2,
            "tag": "error_invalid_args",
        },
        {"kind": "create_no_args", "tail": [], "exit": 1, "tag": "error_invalid_args"},
        {
            "kind": "create_extra_bad_flag",
            "tail": ["-f", "<pod-manifest>", "--invalid-flag"],
            "exit": 2,
            "tag": "error_invalid_args",
        },
        {
            "kind": "create_namespace_bare_kube_system",
            "tail": ["namespace", "<resource-3>"],
            "exit": 0,
            "tag": "happy_path",
        },
    ],
    "describe": [
        {
            "kind": "describe_pod",
            "tail": ["pod", "<resource>", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "describe_pod_namespace_long",
            "tail": ["pod", "<resource>", "--namespace", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "describe_deployment",
            "tail": ["deployment", "<resource>", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "describe_namespace",
            "tail": ["namespace", "<resource>"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "describe_pod_default_ns",
            "tail": ["pod", "<resource>"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "describe_deployment_default_ns",
            "tail": ["deployment", "<resource>"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "describe_pod_kube_system",
            "tail": ["pod", "<resource>", "-n", "kube-system"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "describe_deployment_kube_system",
            "tail": ["deployment", "<resource>", "-n", "kube-system"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "describe_pod_test_ns",
            "tail": ["pod", "<resource>", "-n", "test-ns"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "describe_deployment_test_ns",
            "tail": ["deployment", "<resource>", "-n", "test-ns"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "describe_pod_missing",
            "tail": ["pod", "<nonexistent>", "-n", "default"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "describe_deployment_missing",
            "tail": ["deployment", "<nonexistent>", "-n", "default"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "describe_namespace_missing",
            "tail": ["namespace", "<nonexistent>"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "describe_pod_missing_default_ns",
            "tail": ["pod", "<nonexistent>"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "describe_deployment_missing_default_ns",
            "tail": ["deployment", "<nonexistent>"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "describe_invalid_flag",
            "tail": ["pods", "<resource>", "--invalid-flag"],
            "exit": 2,
            "tag": "error_invalid_args",
        },
        {
            "kind": "describe_invalid_flag_alt",
            "tail": ["pod", "<resource>", "--bogus"],
            "exit": 2,
            "tag": "error_invalid_args",
        },
        {"kind": "describe_no_args", "tail": [], "exit": 1, "tag": "error_invalid_args"},
        {"kind": "describe_only_kind", "tail": ["pod"], "exit": 1, "tag": "error_invalid_args"},
        {
            "kind": "describe_unknown_kind",
            "tail": ["invalidkind", "<resource>", "-n", "default"],
            "exit": 1,
            "tag": "error_invalid_args",
        },
    ],
    "patch": [
        {
            "kind": "patch_pod_label",
            "tail": [
                "pod",
                "<resource>",
                "-p",
                '{"metadata":{"labels":{"env":"prod"}}}',
                "-n",
                "default",
            ],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "patch_pod_patch_long",
            "tail": [
                "pod",
                "<resource>",
                "--patch",
                '{"metadata":{"labels":{"env":"prod"}}}',
                "-n",
                "default",
            ],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "patch_deployment_replicas_2",
            "tail": ["deployment", "<resource>", "-p", '{"spec":{"replicas":2}}', "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "patch_deployment_replicas_3",
            "tail": ["deployment", "<resource>", "-p", '{"spec":{"replicas":3}}', "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "patch_pod_type_strategic",
            "tail": ["pod", "<resource>", "--type", "strategic", "-p", "{}", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "patch_pod_type_merge",
            "tail": ["pod", "<resource>", "--type", "merge", "-p", "{}", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "patch_pod_type_json",
            "tail": ["pod", "<resource>", "--type", "json", "-p", "[]", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "patch_deployment_type_strategic",
            "tail": [
                "deployment",
                "<resource>",
                "--type",
                "strategic",
                "-p",
                "{}",
                "-n",
                "default",
            ],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "patch_deployment_type_merge",
            "tail": ["deployment", "<resource>", "--type", "merge", "-p", "{}", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "patch_deployment_type_json",
            "tail": ["deployment", "<resource>", "--type", "json", "-p", "[]", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "patch_pod_kube_system",
            "tail": ["pod", "<resource>", "-p", "{}", "-n", "kube-system"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "patch_deployment_namespace_long",
            "tail": ["deployment", "<resource>", "-p", "{}", "--namespace", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "patch_pod_missing",
            "tail": ["pod", "<nonexistent>", "-p", "{}", "-n", "default"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "patch_deployment_missing",
            "tail": ["deployment", "<nonexistent>", "-p", "{}", "-n", "default"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "patch_pod_missing_default_ns",
            "tail": ["pod", "<nonexistent>", "-p", "{}"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "patch_invalid_flag",
            "tail": ["pod", "<resource>", "--invalid-flag"],
            "exit": 2,
            "tag": "error_invalid_args",
        },
        {
            "kind": "patch_no_patch_flag",
            "tail": ["pod", "<resource>", "-n", "default"],
            "exit": 1,
            "tag": "error_invalid_args",
        },
        {"kind": "patch_no_args", "tail": [], "exit": 1, "tag": "error_invalid_args"},
        {"kind": "patch_only_kind", "tail": ["pod"], "exit": 1, "tag": "error_invalid_args"},
        {
            "kind": "patch_unknown_kind",
            "tail": ["invalidkind", "<resource>", "-p", "{}", "-n", "default"],
            "exit": 1,
            "tag": "error_invalid_args",
        },
    ],
    "scale": [
        {
            "kind": "scale_deployment_3",
            "tail": ["deployment", "<resource>", "--replicas=3", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "scale_deployment_1",
            "tail": ["deployment", "<resource>", "--replicas=1", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "scale_deployment_0",
            "tail": ["deployment", "<resource>", "--replicas=0", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "scale_deployment_5",
            "tail": ["deployment", "<resource>", "--replicas=5", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "scale_deployment_10",
            "tail": ["deployment", "<resource>", "--replicas=10", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "scale_deployment_namespace_long",
            "tail": ["deployment", "<resource>", "--replicas=2", "--namespace", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "scale_deployment_kube_system",
            "tail": ["deployment", "<resource>", "--replicas=2", "-n", "kube-system"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "scale_deployment_default_ns",
            "tail": ["deployment", "<resource>", "--replicas=2"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "scale_statefulset_2",
            "tail": ["statefulset", "<resource>", "--replicas=2", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "scale_statefulset_3",
            "tail": ["statefulset", "<resource>", "--replicas=3", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "scale_statefulset_0",
            "tail": ["statefulset", "<resource>", "--replicas=0", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "scale_statefulset_default_ns",
            "tail": ["statefulset", "<resource>", "--replicas=1"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "scale_deployment_missing",
            "tail": ["deployment", "<nonexistent>", "--replicas=2", "-n", "default"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "scale_statefulset_missing",
            "tail": ["statefulset", "<nonexistent>", "--replicas=2", "-n", "default"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "scale_deployment_missing_default_ns",
            "tail": ["deployment", "<nonexistent>", "--replicas=3"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "scale_invalid_flag",
            "tail": ["deployment", "<resource>", "--invalid-flag"],
            "exit": 2,
            "tag": "error_invalid_args",
        },
        {
            "kind": "scale_no_replicas",
            "tail": ["deployment", "<resource>", "-n", "default"],
            "exit": 1,
            "tag": "error_invalid_args",
        },
        {"kind": "scale_no_args", "tail": [], "exit": 1, "tag": "error_invalid_args"},
        {"kind": "scale_only_kind", "tail": ["deployment"], "exit": 1, "tag": "error_invalid_args"},
        {
            "kind": "scale_unscalable_kind",
            "tail": ["pod", "<resource>", "--replicas=2", "-n", "default"],
            "exit": 1,
            "tag": "error_invalid_args",
        },
    ],
    "label": [
        {
            "kind": "label_pod_env",
            "tail": ["pod", "<resource>", "env=prod", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "label_pod_app",
            "tail": ["pod", "<resource>", "app=web", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "label_pod_team",
            "tail": ["pod", "<resource>", "team=frontend", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "label_pod_env_namespace_long",
            "tail": ["pod", "<resource>", "env=prod", "--namespace", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "label_deployment_env",
            "tail": ["deployment", "<resource>", "env=prod", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "label_deployment_app",
            "tail": ["deployment", "<resource>", "app=web", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "label_pod_remove",
            "tail": ["pod", "<resource>", "env-", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "label_pod_multiple",
            "tail": ["pod", "<resource>", "env=prod", "app=web", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "label_deployment_multiple",
            "tail": ["deployment", "<resource>", "env=prod", "app=web", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "label_pod_overwrite",
            "tail": ["pod", "<resource>", "env=dev", "--overwrite", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "label_deployment_overwrite",
            "tail": ["deployment", "<resource>", "env=dev", "--overwrite", "-n", "default"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "label_pod_kube_system",
            "tail": ["pod", "<resource>", "env=prod", "-n", "kube-system"],
            "exit": 0,
            "tag": "happy_path",
        },
        {
            "kind": "label_pod_missing",
            "tail": ["pod", "<nonexistent>", "env=prod", "-n", "default"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "label_deployment_missing",
            "tail": ["deployment", "<nonexistent>", "env=prod", "-n", "default"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "label_pod_missing_default_ns",
            "tail": ["pod", "<nonexistent>", "env=prod"],
            "exit": 1,
            "tag": "error_nonexistent",
        },
        {
            "kind": "label_invalid_flag",
            "tail": ["pod", "<resource>", "env=prod", "--invalid-flag", "-n", "default"],
            "exit": 2,
            "tag": "error_invalid_args",
        },
        {
            "kind": "label_no_kv",
            "tail": ["pod", "<resource>", "-n", "default"],
            "exit": 1,
            "tag": "error_invalid_args",
        },
        {"kind": "label_no_args", "tail": [], "exit": 1, "tag": "error_invalid_args"},
        {"kind": "label_only_kind", "tail": ["pod"], "exit": 1, "tag": "error_invalid_args"},
        {
            "kind": "label_bad_format",
            "tail": ["pod", "<resource>", "not-a-valid-label-format", "-n", "default"],
            "exit": 1,
            "tag": "error_invalid_args",
        },
    ],
}


@register_source("kubectl_cobra_yaml")
class KubectlCobraYamlSource(CommandSourceBackend):
    name: ClassVar[str] = "kubectl_cobra_yaml"
    compatible_sims: ClassVar[frozenset[str]] = frozenset({"kwok", "kind"})
    accepted_exit_codes: ClassVar[frozenset[int]] = frozenset({0, 1, 2})
    stdout_shape_regex: ClassVar[str] = (
        r"^\S+(?:/\S+)?\s+(created|configured|deleted|scaled|edited|patched|labeled|"
        r"annotated|drained|cordoned|uncordoned|approved|denied|rolled|restarted|"
        r"paused|resumed|exposed|autoscaled)"
    )
    reference_binary: ClassVar[str] = "kubectl"
    unsupported_verbs: ClassVar[frozenset[str]] = frozenset(
        {"logs", "exec", "port-forward", "attach", "top", "cp"}
    )

    @classmethod
    def extract_spec(
        cls,
        clone_dir: Path,
        command_prefix: str,
        *,
        repo: str = "kubernetes/kubectl",
        git_sha: str = "",
        yaml_bundle_path: str | Path | None = None,
        envs_root: str | Path | None = None,
    ) -> _E.CliSpec:
        """Load the cobra-doc YAML bundle and return a filtered CliSpec.

        Resolution order for the bundle path:
        1. Explicit ``yaml_bundle_path`` override.
        2. ``<envs_root>/<owner>_<repo>/kubectl_spec.yaml`` when both are set.
        3. ``<clone_dir>/../envs/<owner>_<repo>/kubectl_spec.yaml``.

        Commands whose name is in ``unsupported_verbs`` are dropped so
        downstream synthesis never emits ``kubectl logs`` intents. The
        content-address hash covers the raw bundle bytes (not the parsed
        Python objects) so identical bundles ⇒ identical ``spec_sha256``.
        """
        bundle_path = cls._resolve_bundle_path(
            clone_dir=Path(clone_dir),
            repo=repo,
            explicit=yaml_bundle_path,
            envs_root=envs_root,
        )
        raw_bytes = bundle_path.read_bytes()
        bundle = yaml.safe_load(raw_bytes.decode("utf-8", errors="replace"))
        if not isinstance(bundle, dict):
            raise ValueError(
                f"kubectl bundle at {bundle_path} is not a mapping (got {type(bundle).__name__})"
            )

        metadata = bundle.get("metadata") or {}
        resolved_sha = git_sha or metadata.get("git_sha", "") or ""

        commands_raw = bundle.get("commands") or []
        if not isinstance(commands_raw, list):
            raise ValueError(
                f"kubectl bundle 'commands' must be a list, got {type(commands_raw).__name__}"
            )

        commands: list[_E.CommandSpec] = []
        for entry in commands_raw:
            if not isinstance(entry, dict):
                continue
            spec = cls._parse_command_entry(entry)
            if spec is None:
                continue
            if spec.name in cls.unsupported_verbs:
                continue
            commands.append(spec)

        cli = _E.CliSpec(
            name="kubernetes_kubectl",
            command_prefix=command_prefix,
            repo=repo,
            git_sha=resolved_sha,
            entry_point=str(bundle_path.name),
            tests_dir="",
            commands=commands,
        )
        cli.spec_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        return cli

    @classmethod
    def extract_intents(
        cls,
        spec: _E.CliSpec,
        command: str,
        *,
        max_intents: int | None = None,
    ) -> list[_E.TestIntent]:
        """Synthesise diverse TestIntents for one kubectl subcommand.

        Emits 8-15 per-verb shape-only seeds covering: error_nonexistent
        (always first), error_invalid_args, happy_path in multiple flavours
        (default namespace, explicit --namespace, -o json/yaml/wide,
        label selectors, by-name, all-namespaces), and verb-specific edge
        cases (patch --type variants, scale --replicas=0, label add/remove
        etc.). Grounded in the AWS-CLI-S3 pilot brief in CLIENT.MD (happy
        + error + cross-command state coverage; discriminative shapes).

        Downstream LLM synthesis (kwok translation prompt) rewrites each
        ``raw_source`` block into a concrete pytest body + assertion set.
        """
        if command in cls.unsupported_verbs:
            return []
        cmd_spec = next((c for c in spec.commands if c.name == command), None)
        if cmd_spec is None:
            return []

        prefix = spec.command_prefix
        nonexistent_token = f"nonexistent-{uuid.uuid4().hex[:8]}"
        raw = cls._raw_source_for(cmd_spec, prefix)

        templates = _VERB_TEMPLATES.get(command)
        if templates is None:
            happy_argv = cls._happy_argv_from_example(cmd_spec, prefix)
            templates = [
                {
                    "kind": "error_nonexistent",
                    "tail": [nonexistent_token],
                    "exit": 1,
                    "tag": "error_nonexistent",
                },
                {
                    "kind": "error_invalid_args",
                    "tail": ["--invalid-flag"],
                    "exit": 2,
                    "tag": "error_invalid_args",
                },
                {
                    "kind": "happy_path",
                    "tail": happy_argv[1:] or ["<resource>"],
                    "exit": 0,
                    "tag": "happy_path",
                },
            ]

        intents: list[_E.TestIntent] = []
        for tmpl in templates:
            tail = [t.replace("<nonexistent>", nonexistent_token) for t in tmpl["tail"]]
            intents.append(
                cls._make_intent(
                    spec=cmd_spec,
                    kind=tmpl["kind"],
                    cmdline=[command, *tail],
                    expected_exit=int(tmpl["exit"]),
                    behaviour_tag=tmpl["tag"],
                    raw_source=raw,
                )
            )

        if max_intents is not None:
            intents = intents[:max_intents]
        return intents

    @classmethod
    def _resolve_bundle_path(
        cls,
        *,
        clone_dir: Path,
        repo: str,
        explicit: str | Path | None,
        envs_root: str | Path | None,
    ) -> Path:
        if explicit is not None:
            p = Path(explicit)
            if not p.is_file():
                raise FileNotFoundError(f"yaml_bundle_path not found: {p}")
            return p

        cache_stem = repo.replace("/", "_")
        if envs_root is not None:
            candidate = Path(envs_root) / cache_stem / _DEFAULT_BUNDLE_NAME
            if candidate.is_file():
                return candidate

        candidate = clone_dir.parent / "envs" / cache_stem / _DEFAULT_BUNDLE_NAME
        if candidate.is_file():
            return candidate

        raise FileNotFoundError(
            f"could not locate kubectl YAML bundle for repo={repo!r}; "
            f"pass yaml_bundle_path=<path> or place it at {candidate}"
        )

    @classmethod
    def _parse_command_entry(cls, entry: dict[str, Any]) -> _E.CommandSpec | None:
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            return None
        synopsis = str(entry.get("synopsis") or "")
        flags_raw = entry.get("flags") or []
        flags: list[str] = []
        if isinstance(flags_raw, list):
            for f in flags_raw:
                if not isinstance(f, dict):
                    continue
                fname = f.get("name")
                if isinstance(fname, str) and fname:
                    flags.append(f"--{fname}")
        return _E.CommandSpec(name=name, synopsis=synopsis, args=[], flags=flags)

    @classmethod
    def _happy_argv_from_example(cls, cmd_spec: _E.CommandSpec, prefix: str) -> list[str]:
        example = getattr(cmd_spec, "_example", "") or ""
        if example:
            verb_first = f"{cmd_spec.name} {prefix}"
            resource_first = f"{prefix} {cmd_spec.name}"
            for line in example.splitlines():
                stripped = line.strip().lstrip("#").strip()
                if stripped.startswith(verb_first):
                    tokens = stripped.split()
                    if len(tokens) >= 2 and tokens[0] == cmd_spec.name:
                        return [cmd_spec.name, *tokens[1:]]
                if stripped.startswith(resource_first):
                    tokens = stripped.split()
                    if len(tokens) >= 2 and tokens[0] == prefix:
                        return [cmd_spec.name, *tokens[2:]]
        return [cmd_spec.name, "<resource>"]

    @classmethod
    def _raw_source_for(cls, cmd_spec: _E.CommandSpec, prefix: str) -> str:
        parts = [f"Command: {prefix} {cmd_spec.name}"]
        if cmd_spec.synopsis:
            parts.append("")
            parts.append(cmd_spec.synopsis)
        if cmd_spec.flags:
            parts.append("")
            parts.append("Flags: " + " ".join(cmd_spec.flags[:10]))
        return "\n".join(parts)

    @classmethod
    def _make_intent(
        cls,
        *,
        spec: _E.CommandSpec,
        kind: str,
        cmdline: list[str],
        expected_exit: int,
        behaviour_tag: str,
        raw_source: str,
    ) -> _E.TestIntent:
        h = hashlib.sha256()
        h.update(spec.name.encode())
        h.update(b"\0")
        h.update(kind.encode())
        return _E.TestIntent(
            source_file="kubectl_spec.yaml",
            test_name=f"kubectl_{spec.name.replace('-', '_')}_{kind}",
            source_method_sha256=h.hexdigest(),
            command=spec.name,
            cmdline_template=cmdline,
            expected_exit=expected_exit,
            expected_state_calls=[],
            expected_stdout_pattern=None,
            behaviour_tag=behaviour_tag,  # type: ignore[arg-type]
            raw_source=raw_source,
        )
