def test_label_persistentvolumeclaim_0065_add_app(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: PersistentVolumeClaim\nmetadata:\n  name: lpe-0065\n  namespace: default\nspec:\n  accessModes: [ReadWriteOnce]\n  resources:\n    requests:\n      storage: 100Mi\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "persistentvolumeclaim", "lpe-0065", "app=api", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "lpe-0065" in result.stdout
