def test_label_secret_0040_add_region(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Secret\nmetadata:\n  name: lse-0040\n  namespace: default\ntype: Opaque\nstringData:\n  token: s3cret\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "secret", "lse-0040", "region=us-west", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "lse-0040" in result.stdout
