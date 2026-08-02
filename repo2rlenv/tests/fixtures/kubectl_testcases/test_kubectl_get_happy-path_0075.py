def test_get_limitrange_0075_output_custom(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: LimitRange\nmetadata:\n  name: gfli-0075\n  namespace: default\nspec:\n  limits:\n  - type: Container\n    default: {cpu: 100m}\n    defaultRequest: {cpu: 50m}\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "limitrange", "gfli-0075", "-n", "default", "-o", "custom-columns=NAME:.metadata.name")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
