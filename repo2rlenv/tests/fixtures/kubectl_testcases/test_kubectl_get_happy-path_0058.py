def test_get_persistentvolumeclaim_0058_output_yaml(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: PersistentVolumeClaim\nmetadata:\n  name: gfpe-0058\n  namespace: default\nspec:\n  accessModes: [ReadWriteOnce]\n  resources:\n    requests:\n      storage: 100Mi\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "persistentvolumeclaim", "gfpe-0058", "-n", "default", "-o", "yaml")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
