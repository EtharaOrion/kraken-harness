def test_describe_configmap_0206_show_events(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: esco-0206\n  namespace: default\ndata:\n  k1: v1\n  k2: v2\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "configmap", "esco-0206", "-n", "default", "--show-events=true")
    assert result.returncode == 0, result.stderr
    assert "esco-0206" in result.stdout
