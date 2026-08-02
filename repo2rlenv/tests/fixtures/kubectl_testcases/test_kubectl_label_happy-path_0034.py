def test_label_configmap_0034_add_app(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: lco-0034\n  namespace: default\ndata:\n  k1: v1\n  k2: v2\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "configmap", "lco-0034", "app=web", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "lco-0034" in result.stdout
