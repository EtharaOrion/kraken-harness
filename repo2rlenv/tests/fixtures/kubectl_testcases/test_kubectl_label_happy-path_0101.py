def test_label_statefulset_0101_add_region(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: StatefulSet\nmetadata:\n  name: lst-0101\n  namespace: default\nspec:\n  replicas: 1\n  serviceName: lst-0101-svc\n  selector: {matchLabels: {app: lst-0101}}\n  template:\n    metadata:\n      labels: {app: lst-0101}\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "statefulset", "lst-0101", "region=eu-central", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "lst-0101" in result.stdout
