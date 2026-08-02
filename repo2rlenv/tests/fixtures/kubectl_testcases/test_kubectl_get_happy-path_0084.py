def test_get_statefulset_0084_output_wide(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: StatefulSet\nmetadata:\n  name: gfst-0084\n  namespace: default\nspec:\n  replicas: 1\n  serviceName: gfst-0084-svc\n  selector: {matchLabels: {app: gfst-0084}}\n  template:\n    metadata:\n      labels: {app: gfst-0084}\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "statefulset", "gfst-0084", "-n", "default", "-o", "wide")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
