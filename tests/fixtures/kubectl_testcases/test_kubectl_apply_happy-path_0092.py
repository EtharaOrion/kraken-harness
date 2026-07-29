def test_apply_configmap_0092_view_last_applied(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: alco-0092\n  namespace: default\ndata:\n  k1: v1\n  k2: v2\n')
    seed = cli("apply", "-f", str(manifest))
    assert seed.returncode == 0, seed.stderr
    result = cli("apply", "view-last-applied", "configmap", "alco-0092", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "alco-0092" in result.stdout
