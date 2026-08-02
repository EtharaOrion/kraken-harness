def test_describe_statefulset_0015_by_name(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: StatefulSet\nmetadata:\n  name: est-0015\n  namespace: default\nspec:\n  replicas: 1\n  serviceName: est-0015-svc\n  selector: {matchLabels: {app: est-0015}}\n  template:\n    metadata:\n      labels: {app: est-0015}\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "statefulset", "est-0015", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "est-0015" in result.stdout
