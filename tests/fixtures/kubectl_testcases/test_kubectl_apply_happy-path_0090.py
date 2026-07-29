def test_apply_rolebinding_0090_output_yaml(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: rbac.authorization.k8s.io/v1\nkind: RoleBinding\nmetadata:\n  name: aoro-0090\n  namespace: default\nroleRef:\n  apiGroup: rbac.authorization.k8s.io\n  kind: Role\n  name: view\nsubjects:\n- kind: ServiceAccount\n  name: default\n  namespace: default\n')
    result = cli("apply", "-f", str(manifest), "-o", "yaml")
    assert result.returncode == 0, result.stderr
    assert "aoro-0090" in result.stdout
