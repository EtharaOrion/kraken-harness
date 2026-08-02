def test_get_storageclass_0151_output_name(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: storage.k8s.io/v1\nkind: StorageClass\nmetadata:\n  name: gfst-0151\nprovisioner: kubernetes.io/no-provisioner\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "storageclass", "gfst-0151", "-n", "default", "-o", "name")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
