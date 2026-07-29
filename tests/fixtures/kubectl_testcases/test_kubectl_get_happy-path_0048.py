def test_get_secret_0048_output_wide(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Secret\nmetadata:\n  name: gfse-0048\n  namespace: default\ntype: Opaque\nstringData:\n  token: s3cret\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "secret", "gfse-0048", "-n", "default", "-o", "wide")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
