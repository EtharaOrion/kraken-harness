def test_describe_pods_0284_by_selector(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: el-0284\n  namespace: default\n  labels:\n    team: "eL0284"\nspec:\n  containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "pods", "-l", "team=eL0284", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "el-0284" in result.stdout
