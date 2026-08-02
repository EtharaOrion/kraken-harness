def test_create_service_0420_ok(cli, k8s_client):
    result = cli("create", 'service', 'loadbalancer', 'cse-0420', '--tcp=80:80', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cse-0420" in result.stdout
    names = {o.metadata.name for o in k8s_client.list_namespaced_service(namespace="default").items}
    assert "cse-0420" in names
