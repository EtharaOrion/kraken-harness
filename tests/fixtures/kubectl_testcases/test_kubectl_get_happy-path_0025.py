def test_get_persistentvolume_0025_by_name(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: PersistentVolume\nmetadata:\n  name: gpe-0025\nspec:\n  capacity: {storage: 100Mi}\n  accessModes: [ReadWriteOnce]\n  hostPath: {path: /tmp/data}\n  persistentVolumeReclaimPolicy: Retain\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "persistentvolume", "gpe-0025", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "gpe-0025" in result.stdout
    names = {o.metadata.name for o in k8s_client.list_persistent_volume().items}
    assert "gpe-0025" in names
