def test_describe_serviceaccount_0192_show_events(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: esse-0192\n  namespace: default\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "serviceaccount", "esse-0192", "-n", "default", "--show-events=true")
    assert result.returncode == 0, result.stderr
    assert "esse-0192" in result.stdout
