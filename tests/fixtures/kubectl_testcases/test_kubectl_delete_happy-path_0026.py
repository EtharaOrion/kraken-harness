def test_delete_storageclass_0026_by_name(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: storage.k8s.io/v1\nkind: StorageClass\nmetadata:\n  name: dst-0026\nprovisioner: kubernetes.io/no-provisioner\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("delete", "storageclass", "dst-0026", "-n", "default")
    assert result.returncode == 0, result.stderr
