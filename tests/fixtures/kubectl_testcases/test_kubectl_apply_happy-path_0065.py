def test_apply_resourcequota_0065_dryrun_server(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ResourceQuota\nmetadata:\n  name: asre-0065\n  namespace: default\nspec:\n  hard:\n    pods: "10"\n')
    result = cli("apply", "-f", str(manifest), "--dry-run=server")
    assert result.returncode == 0, result.stderr
    assert "asre-0065" in result.stdout
