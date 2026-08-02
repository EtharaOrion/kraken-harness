def test_patch_limitrange_0093_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: LimitRange\nmetadata:\n  name: pili-0093\n  namespace: default\nspec:\n  limits:\n  - type: Container\n    default: {cpu: 100m}\n    defaultRequest: {cpu: 50m}\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    r1 = cli("patch", "limitrange", "pili-0093", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x93"}}}')
    assert r1.returncode == 0, r1.stderr
    r2 = cli("patch", "limitrange", "pili-0093", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x93"}}}')
    assert r2.returncode == 0, r2.stderr
