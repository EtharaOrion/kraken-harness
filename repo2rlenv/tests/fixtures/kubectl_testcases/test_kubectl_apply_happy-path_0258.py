def test_apply_configmap_0258_creates_alt(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: azco-0258\n  namespace: default\ndata:\n  k1: v1\n  k2: v2\n')
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert "azco-0258" in result.stdout
