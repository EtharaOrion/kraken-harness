def test_patch_deployment_0032_json(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: pde-0032\n  namespace: default\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      app: pde-0032\n  template:\n    metadata:\n      labels:\n        app: pde-0032\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "deployment", "pde-0032", "-n", "default", "--type=json", "-p", '[{"op":"add","path":"/metadata/labels/lane","value":"c32"}]')
    assert result.returncode == 0, result.stderr
    assert "pde-0032" in result.stdout
