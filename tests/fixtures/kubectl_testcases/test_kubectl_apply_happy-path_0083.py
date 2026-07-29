def test_apply_deployment_0083_output_yaml(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: aode-0083\n  namespace: default\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      app: aode-0083\n  template:\n    metadata:\n      labels:\n        app: aode-0083\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    result = cli("apply", "-f", str(manifest), "-o", "yaml")
    assert result.returncode == 0, result.stderr
    assert "aode-0083" in result.stdout
