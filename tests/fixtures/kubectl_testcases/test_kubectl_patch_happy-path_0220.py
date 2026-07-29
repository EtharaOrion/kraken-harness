def test_patch_resourcequota_0220_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ResourceQuota\nmetadata:\n  name: pire-0220\n  namespace: default\nspec:\n  hard:\n    pods: "10"\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    r1 = cli("patch", "resourcequota", "pire-0220", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x220"}}}')
    assert r1.returncode == 0, r1.stderr
    r2 = cli("patch", "resourcequota", "pire-0220", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x220"}}}')
    assert r2.returncode == 0, r2.stderr
