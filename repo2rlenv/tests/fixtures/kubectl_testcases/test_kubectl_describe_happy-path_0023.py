def test_describe_clusterrole_0023_by_name(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: rbac.authorization.k8s.io/v1\nkind: ClusterRole\nmetadata:\n  name: ecl-0023\nrules:\n- apiGroups: [""]\n  resources: [pods]\n  verbs: [get, list]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "clusterrole", "ecl-0023", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "ecl-0023" in result.stdout
