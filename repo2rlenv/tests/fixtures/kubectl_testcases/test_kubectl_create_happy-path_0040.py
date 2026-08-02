def test_create_configmap_0040_ok(cli, k8s_client):
    result = cli("create", 'configmap', 'cco-0040', '--from-literal=k=v', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cco-0040" in result.stdout
    names = {o.metadata.name for o in k8s_client.list_namespaced_config_map(namespace="default").items}
    assert "cco-0040" in names
