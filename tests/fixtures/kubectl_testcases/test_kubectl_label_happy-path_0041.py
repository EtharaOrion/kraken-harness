def test_label_secret_0041_add_region(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Secret\nmetadata:\n  name: lse-0041\n  namespace: default\ntype: Opaque\nstringData:\n  token: s3cret\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "secret", "lse-0041", "region=eu-central", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "lse-0041" in result.stdout
