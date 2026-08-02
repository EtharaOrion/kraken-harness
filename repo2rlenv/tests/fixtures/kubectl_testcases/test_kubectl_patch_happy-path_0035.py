def test_patch_statefulset_0035_merge(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: StatefulSet\nmetadata:\n  name: pst-0035\n  namespace: default\nspec:\n  replicas: 1\n  serviceName: pst-0035-svc\n  selector: {matchLabels: {app: pst-0035}}\n  template:\n    metadata:\n      labels: {app: pst-0035}\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "statefulset", "pst-0035", "-n", "default", "--type=merge", "-p", '{"metadata":{"labels":{"lane":"c35"}}}')
    assert result.returncode == 0, result.stderr
    assert "pst-0035" in result.stdout
