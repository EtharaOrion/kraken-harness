def test_apply_deployment_0216_creates_alt(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: azde-0216\n  namespace: default\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      app: azde-0216\n  template:\n    metadata:\n      labels:\n        app: azde-0216\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert "azde-0216" in result.stdout
