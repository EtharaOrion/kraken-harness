def test_label_deployment_0090_add_region(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: lde-0090\n  namespace: default\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      app: lde-0090\n  template:\n    metadata:\n      labels:\n        app: lde-0090\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "deployment", "lde-0090", "region=us-west", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "lde-0090" in result.stdout
