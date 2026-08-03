def test_get_statefulset_0082_output_yaml(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: StatefulSet\nmetadata:\n  name: gfst-0082\n  namespace: default\nspec:\n  replicas: 1\n  serviceName: gfst-0082-svc\n  selector: {matchLabels: {app: gfst-0082}}\n  template:\n    metadata:\n      labels: {app: gfst-0082}\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "statefulset", "gfst-0082", "-n", "default", "-o", "yaml")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
