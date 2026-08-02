def test_get_storageclass_0153_output_custom(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: storage.k8s.io/v1\nkind: StorageClass\nmetadata:\n  name: gfst-0153\nprovisioner: kubernetes.io/no-provisioner\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "storageclass", "gfst-0153", "-n", "default", "-o", "custom-columns=NAME:.metadata.name")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
