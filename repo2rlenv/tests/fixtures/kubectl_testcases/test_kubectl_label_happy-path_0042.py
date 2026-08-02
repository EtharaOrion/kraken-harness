def test_label_secret_0042_add_team(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Secret\nmetadata:\n  name: lse-0042\n  namespace: default\ntype: Opaque\nstringData:\n  token: s3cret\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "secret", "lse-0042", "team=platform", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "lse-0042" in result.stdout
