def test_delete_deployment_0014_by_name(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: dde-0014\n  namespace: default\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      app: dde-0014\n  template:\n    metadata:\n      labels:\n        app: dde-0014\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("delete", "deployment", "dde-0014", "-n", "default")
    assert result.returncode == 0, result.stderr
