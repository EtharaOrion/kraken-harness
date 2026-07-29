def test_apply_deployment_0051_dryrun_client(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: adde-0051\n  namespace: default\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      app: adde-0051\n  template:\n    metadata:\n      labels:\n        app: adde-0051\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    result = cli("apply", "-f", str(manifest), "--dry-run=client")
    assert result.returncode == 0, result.stderr
    assert "adde-0051" in result.stdout
