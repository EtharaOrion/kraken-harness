def test_apply_deployment_0014_creates(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: ade-0014\n  namespace: default\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      app: ade-0014\n  template:\n    metadata:\n      labels:\n        app: ade-0014\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert "ade-0014" in result.stdout
