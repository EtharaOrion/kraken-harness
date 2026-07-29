def test_describe_statefulset_0229_show_events(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: StatefulSet\nmetadata:\n  name: esst-0229\n  namespace: default\nspec:\n  replicas: 1\n  serviceName: esst-0229-svc\n  selector: {matchLabels: {app: esst-0229}}\n  template:\n    metadata:\n      labels: {app: esst-0229}\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "statefulset", "esst-0229", "-n", "default", "--show-events=true")
    assert result.returncode == 0, result.stderr
    assert "esst-0229" in result.stdout
