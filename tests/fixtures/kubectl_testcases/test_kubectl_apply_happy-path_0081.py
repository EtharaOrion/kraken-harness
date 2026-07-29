def test_apply_resourcequota_0081_output_yaml(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ResourceQuota\nmetadata:\n  name: aore-0081\n  namespace: default\nspec:\n  hard:\n    pods: "10"\n')
    result = cli("apply", "-f", str(manifest), "-o", "yaml")
    assert result.returncode == 0, result.stderr
    assert "aore-0081" in result.stdout
