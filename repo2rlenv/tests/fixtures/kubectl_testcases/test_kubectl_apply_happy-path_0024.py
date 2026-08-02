def test_apply_persistentvolume_0024_creates(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: PersistentVolume\nmetadata:\n  name: ape-0024\nspec:\n  capacity: {storage: 100Mi}\n  accessModes: [ReadWriteOnce]\n  hostPath: {path: /tmp/data}\n  persistentVolumeReclaimPolicy: Retain\n')
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert "ape-0024" in result.stdout
    names = {o.metadata.name for o in k8s_client.list_persistent_volume().items}
    assert "ape-0024" in names
