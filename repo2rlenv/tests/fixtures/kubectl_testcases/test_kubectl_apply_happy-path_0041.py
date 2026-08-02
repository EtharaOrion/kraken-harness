def test_apply_role_0041_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: rbac.authorization.k8s.io/v1\nkind: Role\nmetadata:\n  name: airo-0041\n  namespace: default\nrules:\n- apiGroups: [""]\n  resources: [pods]\n  verbs: [get, list]\n')
    r1 = cli("apply", "-f", str(manifest))
    assert r1.returncode == 0, r1.stderr
    r2 = cli("apply", "-f", str(manifest))
    assert r2.returncode == 0, r2.stderr
