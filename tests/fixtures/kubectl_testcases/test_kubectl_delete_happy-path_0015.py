def test_delete_statefulset_0015_by_name(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: StatefulSet\nmetadata:\n  name: dst-0015\n  namespace: default\nspec:\n  replicas: 1\n  serviceName: dst-0015-svc\n  selector: {matchLabels: {app: dst-0015}}\n  template:\n    metadata:\n      labels: {app: dst-0015}\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("delete", "statefulset", "dst-0015", "-n", "default")
    assert result.returncode == 0, result.stderr
