def test_get_persistentvolume_0142_output_yaml(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: PersistentVolume\nmetadata:\n  name: gfpe-0142\nspec:\n  capacity: {storage: 100Mi}\n  accessModes: [ReadWriteOnce]\n  hostPath: {path: /tmp/data}\n  persistentVolumeReclaimPolicy: Retain\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "persistentvolume", "gfpe-0142", "-n", "default", "-o", "yaml")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
