def test_apply_pod_0075_output_yaml(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: aopo-0075\n  namespace: default\nspec:\n  containers: [{name: c, image: nginx}]\n')
    result = cli("apply", "-f", str(manifest), "-o", "yaml")
    assert result.returncode == 0, result.stderr
    assert "aopo-0075" in result.stdout
