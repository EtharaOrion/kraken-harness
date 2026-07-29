def test_get_persistentvolumeclaim_0011_by_name(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: PersistentVolumeClaim\nmetadata:\n  name: gpe-0011\n  namespace: default\nspec:\n  accessModes: [ReadWriteOnce]\n  resources:\n    requests:\n      storage: 100Mi\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "persistentvolumeclaim", "gpe-0011", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "gpe-0011" in result.stdout
    names = {o.metadata.name for o in k8s_client.list_namespaced_persistent_volume_claim(namespace="default").items}
    assert "gpe-0011" in names
