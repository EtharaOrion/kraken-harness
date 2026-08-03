def test_get_deployment_0079_output_name(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: gfde-0079\n  namespace: default\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      app: gfde-0079\n  template:\n    metadata:\n      labels:\n        app: gfde-0079\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "deployment", "gfde-0079", "-n", "default", "-o", "name")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
