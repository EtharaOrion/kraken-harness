def test_patch_persistentvolumeclaim_0235_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: PersistentVolumeClaim\nmetadata:\n  name: pipe-0235\n  namespace: default\nspec:\n  accessModes: [ReadWriteOnce]\n  resources:\n    requests:\n      storage: 100Mi\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    r1 = cli("patch", "persistentvolumeclaim", "pipe-0235", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x235"}}}')
    assert r1.returncode == 0, r1.stderr
    r2 = cli("patch", "persistentvolumeclaim", "pipe-0235", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x235"}}}')
    assert r2.returncode == 0, r2.stderr
