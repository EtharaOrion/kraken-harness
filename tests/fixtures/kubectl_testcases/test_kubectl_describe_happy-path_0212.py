def test_describe_deployment_0212_show_events(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: esde-0212\n  namespace: default\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      app: esde-0212\n  template:\n    metadata:\n      labels:\n        app: esde-0212\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "deployment", "esde-0212", "-n", "default", "--show-events=true")
    assert result.returncode == 0, result.stderr
    assert "esde-0212" in result.stdout
