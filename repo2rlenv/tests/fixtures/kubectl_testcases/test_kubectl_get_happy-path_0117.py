def test_get_role_0117_output_custom(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: rbac.authorization.k8s.io/v1\nkind: Role\nmetadata:\n  name: gfro-0117\n  namespace: default\nrules:\n- apiGroups: [""]\n  resources: [pods]\n  verbs: [get, list]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "role", "gfro-0117", "-n", "default", "-o", "custom-columns=NAME:.metadata.name")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
