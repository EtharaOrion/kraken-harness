def test_patch_serviceaccount_0074_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: pise-0074\n  namespace: default\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    r1 = cli("patch", "serviceaccount", "pise-0074", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x74"}}}')
    assert r1.returncode == 0, r1.stderr
    r2 = cli("patch", "serviceaccount", "pise-0074", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x74"}}}')
    assert r2.returncode == 0, r2.stderr
