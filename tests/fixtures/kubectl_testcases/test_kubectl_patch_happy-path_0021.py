def test_patch_persistentvolumeclaim_0021_strategic(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: PersistentVolumeClaim\nmetadata:\n  name: ppe-0021\n  namespace: default\nspec:\n  accessModes: [ReadWriteOnce]\n  resources:\n    requests:\n      storage: 100Mi\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "persistentvolumeclaim", "ppe-0021", "-n", "default", "-p", '{"metadata":{"labels":{"lane":"a21"}}}')
    assert result.returncode == 0, result.stderr
    assert "ppe-0021" in result.stdout
