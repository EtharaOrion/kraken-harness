def test_delete_statefulset_0435_by_file(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: StatefulSet\nmetadata:\n  name: dfst-0435\n  namespace: default\nspec:\n  replicas: 1\n  serviceName: dfst-0435-svc\n  selector: {matchLabels: {app: dfst-0435}}\n  template:\n    metadata:\n      labels: {app: dfst-0435}\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("delete", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
