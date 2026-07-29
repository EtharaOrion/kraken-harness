def test_apply_resourcequota_0049_dryrun_client(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ResourceQuota\nmetadata:\n  name: adre-0049\n  namespace: default\nspec:\n  hard:\n    pods: "10"\n')
    result = cli("apply", "-f", str(manifest), "--dry-run=client")
    assert result.returncode == 0, result.stderr
    assert "adre-0049" in result.stdout
