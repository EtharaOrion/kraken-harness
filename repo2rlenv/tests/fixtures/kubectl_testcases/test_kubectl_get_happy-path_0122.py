def test_get_rolebinding_0122_output_jsonpa(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: rbac.authorization.k8s.io/v1\nkind: RoleBinding\nmetadata:\n  name: gfro-0122\n  namespace: default\nroleRef:\n  apiGroup: rbac.authorization.k8s.io\n  kind: Role\n  name: view\nsubjects:\n- kind: ServiceAccount\n  name: default\n  namespace: default\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "rolebinding", "gfro-0122", "-n", "default", "-o", "jsonpath={.metadata.name}")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
