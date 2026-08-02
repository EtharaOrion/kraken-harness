def test_apply_configmap_0077_output_yaml(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: aoco-0077\n  namespace: default\ndata:\n  k1: v1\n  k2: v2\n')
    result = cli("apply", "-f", str(manifest), "-o", "yaml")
    assert result.returncode == 0, result.stderr
    assert "aoco-0077" in result.stdout
