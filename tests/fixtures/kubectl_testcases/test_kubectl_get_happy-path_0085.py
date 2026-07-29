def test_get_statefulset_0085_output_name(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: StatefulSet\nmetadata:\n  name: gfst-0085\n  namespace: default\nspec:\n  replicas: 1\n  serviceName: gfst-0085-svc\n  selector: {matchLabels: {app: gfst-0085}}\n  template:\n    metadata:\n      labels: {app: gfst-0085}\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "statefulset", "gfst-0085", "-n", "default", "-o", "name")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
