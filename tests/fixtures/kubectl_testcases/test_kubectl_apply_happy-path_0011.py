def test_apply_persistentvolumeclaim_0011_creates(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: PersistentVolumeClaim\nmetadata:\n  name: ape-0011\n  namespace: default\nspec:\n  accessModes: [ReadWriteOnce]\n  resources:\n    requests:\n      storage: 100Mi\n')
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert "ape-0011" in result.stdout
    names = {o.metadata.name for o in k8s_client.list_namespaced_persistent_volume_claim(namespace="default").items}
    assert "ape-0011" in names
