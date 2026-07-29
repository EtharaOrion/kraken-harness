def test_patch_statefulset_0143_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: StatefulSet\nmetadata:\n  name: pist-0143\n  namespace: default\nspec:\n  replicas: 1\n  serviceName: pist-0143-svc\n  selector: {matchLabels: {app: pist-0143}}\n  template:\n    metadata:\n      labels: {app: pist-0143}\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    r1 = cli("patch", "statefulset", "pist-0143", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x143"}}}')
    assert r1.returncode == 0, r1.stderr
    r2 = cli("patch", "statefulset", "pist-0143", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x143"}}}')
    assert r2.returncode == 0, r2.stderr
