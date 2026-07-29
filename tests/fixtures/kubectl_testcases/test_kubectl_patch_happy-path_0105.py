def test_patch_secret_0105_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Secret\nmetadata:\n  name: pise-0105\n  namespace: default\ntype: Opaque\nstringData:\n  token: s3cret\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    r1 = cli("patch", "secret", "pise-0105", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x105"}}}')
    assert r1.returncode == 0, r1.stderr
    r2 = cli("patch", "secret", "pise-0105", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x105"}}}')
    assert r2.returncode == 0, r2.stderr
