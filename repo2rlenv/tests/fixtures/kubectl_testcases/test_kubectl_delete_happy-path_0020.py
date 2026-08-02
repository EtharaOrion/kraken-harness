def test_delete_role_0020_by_name(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: rbac.authorization.k8s.io/v1\nkind: Role\nmetadata:\n  name: dro-0020\n  namespace: default\nrules:\n- apiGroups: [""]\n  resources: [pods]\n  verbs: [get, list]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("delete", "role", "dro-0020", "-n", "default")
    assert result.returncode == 0, result.stderr
