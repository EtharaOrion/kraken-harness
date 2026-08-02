def test_label_statefulset_0102_add_team(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: StatefulSet\nmetadata:\n  name: lst-0102\n  namespace: default\nspec:\n  replicas: 1\n  serviceName: lst-0102-svc\n  selector: {matchLabels: {app: lst-0102}}\n  template:\n    metadata:\n      labels: {app: lst-0102}\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "statefulset", "lst-0102", "team=platform", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "lst-0102" in result.stdout
