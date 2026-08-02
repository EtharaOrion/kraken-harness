def test_label_limitrange_0081_add_region(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: LimitRange\nmetadata:\n  name: lli-0081\n  namespace: default\nspec:\n  limits:\n  - type: Container\n    default: {cpu: 100m}\n    defaultRequest: {cpu: 50m}\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "limitrange", "lli-0081", "region=eu-central", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "lli-0081" in result.stdout
