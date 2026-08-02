def test_label_pod_0007_add_tier(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: lpo-0007\n  namespace: default\nspec:\n  containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "pod", "lpo-0007", "tier=backend", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "lpo-0007" in result.stdout
