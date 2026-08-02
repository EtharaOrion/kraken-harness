def test_patch_rolebinding_0051_strategic(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: rbac.authorization.k8s.io/v1\nkind: RoleBinding\nmetadata:\n  name: pro-0051\n  namespace: default\nroleRef:\n  apiGroup: rbac.authorization.k8s.io\n  kind: Role\n  name: view\nsubjects:\n- kind: ServiceAccount\n  name: default\n  namespace: default\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "rolebinding", "pro-0051", "-n", "default", "-p", '{"metadata":{"labels":{"lane":"a51"}}}')
    assert result.returncode == 0, result.stderr
    assert "pro-0051" in result.stdout
