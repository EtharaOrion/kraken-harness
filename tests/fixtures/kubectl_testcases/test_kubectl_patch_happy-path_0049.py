def test_patch_role_0049_merge(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: rbac.authorization.k8s.io/v1\nkind: Role\nmetadata:\n  name: pro-0049\n  namespace: default\nrules:\n- apiGroups: [""]\n  resources: [pods]\n  verbs: [get, list]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "role", "pro-0049", "-n", "default", "--type=merge", "-p", '{"metadata":{"labels":{"lane":"b49"}}}')
    assert result.returncode == 0, result.stderr
    assert "pro-0049" in result.stdout
