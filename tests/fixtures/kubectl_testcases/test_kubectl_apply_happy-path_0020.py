def test_apply_role_0020_creates(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: rbac.authorization.k8s.io/v1\nkind: Role\nmetadata:\n  name: aro-0020\n  namespace: default\nrules:\n- apiGroups: [""]\n  resources: [pods]\n  verbs: [get, list]\n')
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert "aro-0020" in result.stdout
