def test_apply_configmap_0029_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: aico-0029\n  namespace: default\ndata:\n  k1: v1\n  k2: v2\n')
    r1 = cli("apply", "-f", str(manifest))
    assert r1.returncode == 0, r1.stderr
    r2 = cli("apply", "-f", str(manifest))
    assert r2.returncode == 0, r2.stderr
