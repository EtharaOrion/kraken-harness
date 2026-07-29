def test_describe_secret_0143_show_events(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Secret\nmetadata:\n  name: esse-0143\n  namespace: default\ntype: Opaque\nstringData:\n  token: s3cret\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "secret", "esse-0143", "-n", "default", "--show-events=true")
    assert result.returncode == 0, result.stderr
    assert "esse-0143" in result.stdout
