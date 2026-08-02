def test_get_clusterrolebinding_0140_output_jsonpa(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: rbac.authorization.k8s.io/v1\nkind: ClusterRoleBinding\nmetadata:\n  name: gfcl-0140\nroleRef:\n  apiGroup: rbac.authorization.k8s.io\n  kind: ClusterRole\n  name: view\nsubjects:\n- kind: ServiceAccount\n  name: default\n  namespace: default\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "clusterrolebinding", "gfcl-0140", "-n", "default", "-o", "jsonpath={.metadata.name}")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
