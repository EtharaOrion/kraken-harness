def test_apply_serviceaccount_0047_dryrun_client(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: adse-0047\n  namespace: default\n')
    result = cli("apply", "-f", str(manifest), "--dry-run=client")
    assert result.returncode == 0, result.stderr
    assert "adse-0047" in result.stdout
