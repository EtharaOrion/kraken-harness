def test_label_resourcequota_0073_add_team(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ResourceQuota\nmetadata:\n  name: lre-0073\n  namespace: default\nspec:\n  hard:\n    pods: "10"\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "resourcequota", "lre-0073", "team=data", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "lre-0073" in result.stdout
