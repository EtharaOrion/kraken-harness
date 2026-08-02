def test_patch_rolebinding_0325_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: rbac.authorization.k8s.io/v1\nkind: RoleBinding\nmetadata:\n  name: piro-0325\n  namespace: default\nroleRef:\n  apiGroup: rbac.authorization.k8s.io\n  kind: Role\n  name: view\nsubjects:\n- kind: ServiceAccount\n  name: default\n  namespace: default\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    r1 = cli("patch", "rolebinding", "piro-0325", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x325"}}}')
    assert r1.returncode == 0, r1.stderr
    r2 = cli("patch", "rolebinding", "piro-0325", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x325"}}}')
    assert r2.returncode == 0, r2.stderr
