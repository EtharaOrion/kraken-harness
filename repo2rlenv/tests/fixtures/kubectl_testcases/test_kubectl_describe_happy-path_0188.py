def test_describe_pod_0188_show_events(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: espo-0188\n  namespace: default\nspec:\n  containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "pod", "espo-0188", "-n", "default", "--show-events=true")
    assert result.returncode == 0, result.stderr
    assert "espo-0188" in result.stdout
