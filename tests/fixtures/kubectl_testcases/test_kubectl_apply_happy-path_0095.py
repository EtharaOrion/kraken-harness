def test_apply_serviceaccount_0095_view_last_applied(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: alse-0095\n  namespace: default\n')
    seed = cli("apply", "-f", str(manifest))
    assert seed.returncode == 0, seed.stderr
    result = cli("apply", "view-last-applied", "serviceaccount", "alse-0095", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "alse-0095" in result.stdout
