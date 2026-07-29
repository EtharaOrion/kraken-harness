def test_delete_serviceaccount_0010_by_name(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: dse-0010\n  namespace: default\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("delete", "serviceaccount", "dse-0010", "-n", "default")
    assert result.returncode == 0, result.stderr
    names = {o.metadata.name for o in k8s_client.list_namespaced_service_account(namespace="default").items}
    assert "dse-0010" not in names
