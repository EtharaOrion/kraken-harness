def test_label_persistentvolumeclaim_0057_add_tier(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: PersistentVolumeClaim\nmetadata:\n  name: lpe-0057\n  namespace: default\nspec:\n  accessModes: [ReadWriteOnce]\n  resources:\n    requests:\n      storage: 100Mi\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "persistentvolumeclaim", "lpe-0057", "tier=backend", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "lpe-0057" in result.stdout
