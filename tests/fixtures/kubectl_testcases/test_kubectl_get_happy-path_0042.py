def test_get_configmap_0042_output_wide(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: gfco-0042\n  namespace: default\ndata:\n  k1: v1\n  k2: v2\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "configmap", "gfco-0042", "-n", "default", "-o", "wide")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
