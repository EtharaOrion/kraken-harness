def test_label_deployment_0088_add_env(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: lde-0088\n  namespace: default\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      app: lde-0088\n  template:\n    metadata:\n      labels:\n        app: lde-0088\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "deployment", "lde-0088", "env=prod", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "lde-0088" in result.stdout
