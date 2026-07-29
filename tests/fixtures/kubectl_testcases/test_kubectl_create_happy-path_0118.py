def test_create_serviceaccount_0118_ok(cli, k8s_client):
    result = cli("create", 'serviceaccount', 'cse-0118', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cse-0118" in result.stdout
    names = {o.metadata.name for o in k8s_client.list_namespaced_service_account(namespace="default").items}
    assert "cse-0118" in names
