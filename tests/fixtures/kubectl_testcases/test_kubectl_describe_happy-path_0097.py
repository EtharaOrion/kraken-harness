def test_describe_persistentvolumeclaim_0097_show_events(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: PersistentVolumeClaim\nmetadata:\n  name: espe-0097\n  namespace: default\nspec:\n  accessModes: [ReadWriteOnce]\n  resources:\n    requests:\n      storage: 100Mi\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "persistentvolumeclaim", "espe-0097", "-n", "default", "--show-events=true")
    assert result.returncode == 0, result.stderr
    assert "espe-0097" in result.stdout
