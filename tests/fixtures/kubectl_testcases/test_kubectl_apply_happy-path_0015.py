def test_apply_statefulset_0015_creates(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: StatefulSet\nmetadata:\n  name: ast-0015\n  namespace: default\nspec:\n  replicas: 1\n  serviceName: ast-0015-svc\n  selector: {matchLabels: {app: ast-0015}}\n  template:\n    metadata:\n      labels: {app: ast-0015}\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert "ast-0015" in result.stdout
