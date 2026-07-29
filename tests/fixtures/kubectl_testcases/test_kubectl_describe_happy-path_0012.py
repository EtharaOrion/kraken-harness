def test_describe_resourcequota_0012_by_name(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ResourceQuota\nmetadata:\n  name: ere-0012\n  namespace: default\nspec:\n  hard:\n    pods: "10"\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "resourcequota", "ere-0012", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "ere-0012" in result.stdout
