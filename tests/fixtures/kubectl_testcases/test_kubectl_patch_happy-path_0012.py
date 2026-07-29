def test_patch_configmap_0012_strategic(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: pco-0012\n  namespace: default\ndata:\n  k1: v1\n  k2: v2\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "configmap", "pco-0012", "-n", "default", "-p", '{"metadata":{"labels":{"lane":"a12"}}}')
    assert result.returncode == 0, result.stderr
    assert "pco-0012" in result.stdout
