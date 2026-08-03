def test_apply_statefulset_0084_output_yaml(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: StatefulSet\nmetadata:\n  name: aost-0084\n  namespace: default\nspec:\n  replicas: 1\n  serviceName: aost-0084-svc\n  selector: {matchLabels: {app: aost-0084}}\n  template:\n    metadata:\n      labels: {app: aost-0084}\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    result = cli("apply", "-f", str(manifest), "-o", "yaml")
    assert result.returncode == 0, result.stderr
    assert "aost-0084" in result.stdout
