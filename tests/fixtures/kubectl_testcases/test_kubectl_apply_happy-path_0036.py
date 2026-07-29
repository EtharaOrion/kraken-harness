def test_apply_statefulset_0036_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: StatefulSet\nmetadata:\n  name: aist-0036\n  namespace: default\nspec:\n  replicas: 1\n  serviceName: aist-0036-svc\n  selector: {matchLabels: {app: aist-0036}}\n  template:\n    metadata:\n      labels: {app: aist-0036}\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    r1 = cli("apply", "-f", str(manifest))
    assert r1.returncode == 0, r1.stderr
    r2 = cli("apply", "-f", str(manifest))
    assert r2.returncode == 0, r2.stderr
