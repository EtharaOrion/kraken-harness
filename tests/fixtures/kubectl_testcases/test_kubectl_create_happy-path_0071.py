def test_create_secret_0071_ok(cli, k8s_client):
    result = cli("create", 'secret', 'generic', 'cse-0071', '--from-literal=t=s', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cse-0071" in result.stdout
    names = {o.metadata.name for o in k8s_client.list_namespaced_secret(namespace="default").items}
    assert "cse-0071" in names
