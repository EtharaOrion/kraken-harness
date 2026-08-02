def test_create_configmap_0046_ok(cli, k8s_client):
    result = cli("create", 'configmap', 'cco-0046', '--from-literal=k=v', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cco-0046" in result.stdout
    names = {o.metadata.name for o in k8s_client.list_namespaced_config_map(namespace="default").items}
    assert "cco-0046" in names
