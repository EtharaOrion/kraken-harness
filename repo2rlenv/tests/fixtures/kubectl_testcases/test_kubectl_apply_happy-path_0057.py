def test_apply_role_0057_dryrun_client(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: rbac.authorization.k8s.io/v1\nkind: Role\nmetadata:\n  name: adro-0057\n  namespace: default\nrules:\n- apiGroups: [""]\n  resources: [pods]\n  verbs: [get, list]\n')
    result = cli("apply", "-f", str(manifest), "--dry-run=client")
    assert result.returncode == 0, result.stderr
    assert "adro-0057" in result.stdout
