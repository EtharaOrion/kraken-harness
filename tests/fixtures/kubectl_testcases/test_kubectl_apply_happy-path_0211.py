def test_apply_secret_0211_creates_alt(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Secret\nmetadata:\n  name: azse-0211\n  namespace: default\ntype: Opaque\nstringData:\n  token: s3cret\n')
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert "azse-0211" in result.stdout
