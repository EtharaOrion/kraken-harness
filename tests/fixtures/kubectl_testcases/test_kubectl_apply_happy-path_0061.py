def test_apply_configmap_0061_dryrun_server(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: asco-0061\n  namespace: default\ndata:\n  k1: v1\n  k2: v2\n')
    result = cli("apply", "-f", str(manifest), "--dry-run=server")
    assert result.returncode == 0, result.stderr
    assert "asco-0061" in result.stdout
