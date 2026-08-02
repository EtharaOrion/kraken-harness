def test_describe_limitrange_0147_show_events(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: LimitRange\nmetadata:\n  name: esli-0147\n  namespace: default\nspec:\n  limits:\n  - type: Container\n    default: {cpu: 100m}\n    defaultRequest: {cpu: 50m}\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "limitrange", "esli-0147", "-n", "default", "--show-events=true")
    assert result.returncode == 0, result.stderr
    assert "esli-0147" in result.stdout
