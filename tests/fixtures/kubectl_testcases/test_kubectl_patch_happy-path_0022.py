def test_patch_persistentvolumeclaim_0022_merge(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: PersistentVolumeClaim\nmetadata:\n  name: ppe-0022\n  namespace: default\nspec:\n  accessModes: [ReadWriteOnce]\n  resources:\n    requests:\n      storage: 100Mi\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "persistentvolumeclaim", "ppe-0022", "-n", "default", "--type=merge", "-p", '{"metadata":{"labels":{"lane":"b22"}}}')
    assert result.returncode == 0, result.stderr
    assert "ppe-0022" in result.stdout
