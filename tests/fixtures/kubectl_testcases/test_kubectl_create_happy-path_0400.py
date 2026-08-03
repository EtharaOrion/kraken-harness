def test_create_service_0400_ok(cli, k8s_client):
    result = cli("create", 'service', 'nodeport', 'cse-0400', '--tcp=80:80', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cse-0400" in result.stdout
    names = {o.metadata.name for o in k8s_client.list_namespaced_service(namespace="default").items}
    assert "cse-0400" in names
