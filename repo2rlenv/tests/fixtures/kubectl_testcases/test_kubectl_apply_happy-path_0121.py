def test_apply_statefulset_0121_creates_alt(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: StatefulSet\nmetadata:\n  name: azst-0121\n  namespace: default\nspec:\n  replicas: 1\n  serviceName: azst-0121-svc\n  selector: {matchLabels: {app: azst-0121}}\n  template:\n    metadata:\n      labels: {app: azst-0121}\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert "azst-0121" in result.stdout
