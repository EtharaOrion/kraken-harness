def test_patch_secret_0217_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Secret\nmetadata:\n  name: pise-0217\n  namespace: default\ntype: Opaque\nstringData:\n  token: s3cret\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    r1 = cli("patch", "secret", "pise-0217", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x217"}}}')
    assert r1.returncode == 0, r1.stderr
    r2 = cli("patch", "secret", "pise-0217", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x217"}}}')
    assert r2.returncode == 0, r2.stderr
