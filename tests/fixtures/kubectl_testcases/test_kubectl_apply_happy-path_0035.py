def test_apply_deployment_0035_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: aide-0035\n  namespace: default\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      app: aide-0035\n  template:\n    metadata:\n      labels:\n        app: aide-0035\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    r1 = cli("apply", "-f", str(manifest))
    assert r1.returncode == 0, r1.stderr
    r2 = cli("apply", "-f", str(manifest))
    assert r2.returncode == 0, r2.stderr
