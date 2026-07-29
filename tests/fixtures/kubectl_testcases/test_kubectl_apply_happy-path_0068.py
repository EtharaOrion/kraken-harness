def test_apply_statefulset_0068_dryrun_server(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: StatefulSet\nmetadata:\n  name: asst-0068\n  namespace: default\nspec:\n  replicas: 1\n  serviceName: asst-0068-svc\n  selector: {matchLabels: {app: asst-0068}}\n  template:\n    metadata:\n      labels: {app: asst-0068}\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    result = cli("apply", "-f", str(manifest), "--dry-run=server")
    assert result.returncode == 0, result.stderr
    assert "asst-0068" in result.stdout
