def test_label_pod_0009_add_env(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: lpo-0009\n  namespace: default\nspec:\n  containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "pod", "lpo-0009", "env=staging", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "lpo-0009" in result.stdout
