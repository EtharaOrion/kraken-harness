def test_delete_deployment_0418_by_file(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: dfde-0418\n  namespace: default\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      app: dfde-0418\n  template:\n    metadata:\n      labels:\n        app: dfde-0418\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("delete", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
