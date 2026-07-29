def test_apply_storageclass_0025_creates(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: storage.k8s.io/v1\nkind: StorageClass\nmetadata:\n  name: ast-0025\nprovisioner: kubernetes.io/no-provisioner\n')
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert "ast-0025" in result.stdout
