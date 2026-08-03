def test_get_deployment_0077_output_json(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: gfde-0077\n  namespace: default\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      app: gfde-0077\n  template:\n    metadata:\n      labels:\n        app: gfde-0077\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "deployment", "gfde-0077", "-n", "default", "-o", "json")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
