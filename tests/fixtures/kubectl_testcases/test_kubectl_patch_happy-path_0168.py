def test_patch_configmap_0168_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: pico-0168\n  namespace: default\ndata:\n  k1: v1\n  k2: v2\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    r1 = cli("patch", "configmap", "pico-0168", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x168"}}}')
    assert r1.returncode == 0, r1.stderr
    r2 = cli("patch", "configmap", "pico-0168", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x168"}}}')
    assert r2.returncode == 0, r2.stderr
