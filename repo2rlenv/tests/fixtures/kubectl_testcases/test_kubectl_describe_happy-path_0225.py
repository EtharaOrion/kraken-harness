def test_describe_persistentvolumeclaim_0225_show_events(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: PersistentVolumeClaim\nmetadata:\n  name: espe-0225\n  namespace: default\nspec:\n  accessModes: [ReadWriteOnce]\n  resources:\n    requests:\n      storage: 100Mi\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "persistentvolumeclaim", "espe-0225", "-n", "default", "--show-events=true")
    assert result.returncode == 0, result.stderr
    assert "espe-0225" in result.stdout
