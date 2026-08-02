def test_get_clusterrole_0132_output_wide(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: rbac.authorization.k8s.io/v1\nkind: ClusterRole\nmetadata:\n  name: gfcl-0132\nrules:\n- apiGroups: [""]\n  resources: [pods]\n  verbs: [get, list]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "clusterrole", "gfcl-0132", "-n", "default", "-o", "wide")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
