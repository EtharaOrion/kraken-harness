def test_describe_secret_0009_by_name(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Secret\nmetadata:\n  name: ese-0009\n  namespace: default\ntype: Opaque\nstringData:\n  token: s3cret\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "secret", "ese-0009", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "ese-0009" in result.stdout
