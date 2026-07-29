def test_apply_secret_0094_view_last_applied(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Secret\nmetadata:\n  name: alse-0094\n  namespace: default\ntype: Opaque\nstringData:\n  token: s3cret\n')
    seed = cli("apply", "-f", str(manifest))
    assert seed.returncode == 0, seed.stderr
    result = cli("apply", "view-last-applied", "secret", "alse-0094", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "alse-0094" in result.stdout
