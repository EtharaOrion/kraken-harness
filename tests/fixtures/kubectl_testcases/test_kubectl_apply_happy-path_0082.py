def test_apply_limitrange_0082_output_yaml(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: LimitRange\nmetadata:\n  name: aoli-0082\n  namespace: default\nspec:\n  limits:\n  - type: Container\n    default: {cpu: 100m}\n    defaultRequest: {cpu: 50m}\n')
    result = cli("apply", "-f", str(manifest), "-o", "yaml")
    assert result.returncode == 0, result.stderr
    assert "aoli-0082" in result.stdout
