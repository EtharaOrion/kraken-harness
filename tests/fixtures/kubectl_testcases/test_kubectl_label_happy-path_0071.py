def test_label_resourcequota_0071_add_region(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ResourceQuota\nmetadata:\n  name: lre-0071\n  namespace: default\nspec:\n  hard:\n    pods: "10"\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "resourcequota", "lre-0071", "region=eu-central", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "lre-0071" in result.stdout
