def test_patch_statefulset_0095_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: StatefulSet\nmetadata:\n  name: pist-0095\n  namespace: default\nspec:\n  replicas: 1\n  serviceName: pist-0095-svc\n  selector: {matchLabels: {app: pist-0095}}\n  template:\n    metadata:\n      labels: {app: pist-0095}\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    r1 = cli("patch", "statefulset", "pist-0095", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x95"}}}')
    assert r1.returncode == 0, r1.stderr
    r2 = cli("patch", "statefulset", "pist-0095", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x95"}}}')
    assert r2.returncode == 0, r2.stderr
