def test_apply_deployment_0067_dryrun_server(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: asde-0067\n  namespace: default\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      app: asde-0067\n  template:\n    metadata:\n      labels:\n        app: asde-0067\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    result = cli("apply", "-f", str(manifest), "--dry-run=server")
    assert result.returncode == 0, result.stderr
    assert "asde-0067" in result.stdout
