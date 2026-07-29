def test_describe_resourcequota_0130_show_events(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ResourceQuota\nmetadata:\n  name: esre-0130\n  namespace: default\nspec:\n  hard:\n    pods: "10"\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "resourcequota", "esre-0130", "-n", "default", "--show-events=true")
    assert result.returncode == 0, result.stderr
    assert "esre-0130" in result.stdout
