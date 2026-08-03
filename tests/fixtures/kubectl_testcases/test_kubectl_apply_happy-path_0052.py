def test_apply_statefulset_0052_dryrun_client(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: StatefulSet\nmetadata:\n  name: adst-0052\n  namespace: default\nspec:\n  replicas: 1\n  serviceName: adst-0052-svc\n  selector: {matchLabels: {app: adst-0052}}\n  template:\n    metadata:\n      labels: {app: adst-0052}\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    result = cli("apply", "-f", str(manifest), "--dry-run=client")
    assert result.returncode == 0, result.stderr
    assert "adst-0052" in result.stdout
