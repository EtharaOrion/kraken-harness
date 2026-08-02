def test_delete_serviceaccount_0286_by_file(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: dfse-0286\n  namespace: default\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("delete", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    names = {o.metadata.name for o in k8s_client.list_namespaced_service_account(namespace="default").items}
    assert "dfse-0286" not in names
