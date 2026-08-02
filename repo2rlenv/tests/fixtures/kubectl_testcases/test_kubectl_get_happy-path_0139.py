def test_get_clusterrolebinding_0139_output_name(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: rbac.authorization.k8s.io/v1\nkind: ClusterRoleBinding\nmetadata:\n  name: gfcl-0139\nroleRef:\n  apiGroup: rbac.authorization.k8s.io\n  kind: ClusterRole\n  name: view\nsubjects:\n- kind: ServiceAccount\n  name: default\n  namespace: default\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "clusterrolebinding", "gfcl-0139", "-n", "default", "-o", "name")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
