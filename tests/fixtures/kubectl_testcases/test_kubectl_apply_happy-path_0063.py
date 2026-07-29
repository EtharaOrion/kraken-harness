def test_apply_serviceaccount_0063_dryrun_server(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: asse-0063\n  namespace: default\n')
    result = cli("apply", "-f", str(manifest), "--dry-run=server")
    assert result.returncode == 0, result.stderr
    assert "asse-0063" in result.stdout
