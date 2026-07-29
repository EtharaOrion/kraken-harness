def test_patch_deployment_0030_strategic(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: pde-0030\n  namespace: default\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      app: pde-0030\n  template:\n    metadata:\n      labels:\n        app: pde-0030\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "deployment", "pde-0030", "-n", "default", "-p", '{"metadata":{"labels":{"lane":"a30"}}}')
    assert result.returncode == 0, result.stderr
    assert "pde-0030" in result.stdout
