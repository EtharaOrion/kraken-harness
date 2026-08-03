def test_create_secret_0086_ok(cli, k8s_client):
    result = cli("create", 'secret', 'docker-registry', 'cse-0086', '--docker-username=u', '--docker-password=p', '--docker-email=e@x.com', '--docker-server=x.io', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cse-0086" in result.stdout
    names = {o.metadata.name for o in k8s_client.list_namespaced_secret(namespace="default").items}
    assert "cse-0086" in names
