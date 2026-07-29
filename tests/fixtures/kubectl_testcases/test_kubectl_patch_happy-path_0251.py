def test_patch_persistentvolumeclaim_0251_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: PersistentVolumeClaim\nmetadata:\n  name: pipe-0251\n  namespace: default\nspec:\n  accessModes: [ReadWriteOnce]\n  resources:\n    requests:\n      storage: 100Mi\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    r1 = cli("patch", "persistentvolumeclaim", "pipe-0251", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x251"}}}')
    assert r1.returncode == 0, r1.stderr
    r2 = cli("patch", "persistentvolumeclaim", "pipe-0251", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x251"}}}')
    assert r2.returncode == 0, r2.stderr
