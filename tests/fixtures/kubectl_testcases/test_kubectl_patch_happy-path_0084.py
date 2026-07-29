def test_patch_role_0084_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: rbac.authorization.k8s.io/v1\nkind: Role\nmetadata:\n  name: piro-0084\n  namespace: default\nrules:\n- apiGroups: [""]\n  resources: [pods]\n  verbs: [get, list]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    r1 = cli("patch", "role", "piro-0084", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x84"}}}')
    assert r1.returncode == 0, r1.stderr
    r2 = cli("patch", "role", "piro-0084", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x84"}}}')
    assert r2.returncode == 0, r2.stderr
