def test_create_service_0401_ok(cli, k8s_client):
    result = cli("create", 'service', 'nodeport', 'cse-0401', '--tcp=80:80', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cse-0401" in result.stdout
    names = {o.metadata.name for o in k8s_client.list_namespaced_service(namespace="default").items}
    assert "cse-0401" in names
