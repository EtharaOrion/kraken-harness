def test_get_pod_0033_output_custom(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: gfpo-0033\n  namespace: default\nspec:\n  containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "pod", "gfpo-0033", "-n", "default", "-o", "custom-columns=NAME:.metadata.name")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
