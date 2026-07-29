def test_apply_pod_0043_dryrun_client(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: adpo-0043\n  namespace: default\nspec:\n  containers: [{name: c, image: nginx}]\n')
    result = cli("apply", "-f", str(manifest), "--dry-run=client")
    assert result.returncode == 0, result.stderr
    assert "adpo-0043" in result.stdout
