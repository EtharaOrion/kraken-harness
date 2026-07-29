def test_get_storageclass_0026_by_name(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: storage.k8s.io/v1\nkind: StorageClass\nmetadata:\n  name: gst-0026\nprovisioner: kubernetes.io/no-provisioner\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "storageclass", "gst-0026", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "gst-0026" in result.stdout
