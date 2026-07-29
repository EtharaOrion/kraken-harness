def test_create_service_0444_ok(cli, k8s_client):
    result = cli("create", 'service', 'externalname', 'cse-0444', '--external-name=example.com', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cse-0444" in result.stdout
    names = {o.metadata.name for o in k8s_client.list_namespaced_service(namespace="default").items}
    assert "cse-0444" in names
