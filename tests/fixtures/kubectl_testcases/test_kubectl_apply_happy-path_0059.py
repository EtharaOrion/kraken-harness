def test_apply_pod_0059_dryrun_server(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: aspo-0059\n  namespace: default\nspec:\n  containers: [{name: c, image: nginx}]\n')
    result = cli("apply", "-f", str(manifest), "--dry-run=server")
    assert result.returncode == 0, result.stderr
    assert "aspo-0059" in result.stdout
