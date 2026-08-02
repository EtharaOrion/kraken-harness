def test_create_configmap_0052_ok(cli, k8s_client):
    result = cli("create", 'configmap', 'cco-0052', '--from-literal=k=v', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cco-0052" in result.stdout
    names = {o.metadata.name for o in k8s_client.list_namespaced_config_map(namespace="default").items}
    assert "cco-0052" in names
