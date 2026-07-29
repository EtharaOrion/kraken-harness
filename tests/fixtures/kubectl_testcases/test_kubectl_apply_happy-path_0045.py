def test_apply_configmap_0045_dryrun_client(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: adco-0045\n  namespace: default\ndata:\n  k1: v1\n  k2: v2\n')
    result = cli("apply", "-f", str(manifest), "--dry-run=client")
    assert result.returncode == 0, result.stderr
    assert "adco-0045" in result.stdout
