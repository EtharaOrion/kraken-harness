def test_apply_secret_0009_creates(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Secret\nmetadata:\n  name: ase-0009\n  namespace: default\ntype: Opaque\nstringData:\n  token: s3cret\n')
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert "ase-0009" in result.stdout
    names = {o.metadata.name for o in k8s_client.list_namespaced_secret(namespace="default").items}
    assert "ase-0009" in names
