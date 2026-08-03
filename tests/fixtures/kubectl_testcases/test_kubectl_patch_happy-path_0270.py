def test_patch_deployment_0270_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: pide-0270\n  namespace: default\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      app: pide-0270\n  template:\n    metadata:\n      labels:\n        app: pide-0270\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    r1 = cli("patch", "deployment", "pide-0270", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x270"}}}')
    assert r1.returncode == 0, r1.stderr
    r2 = cli("patch", "deployment", "pide-0270", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x270"}}}')
    assert r2.returncode == 0, r2.stderr
