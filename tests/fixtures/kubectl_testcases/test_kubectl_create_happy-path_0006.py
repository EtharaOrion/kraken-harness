def test_create_namespace_0006_ok(cli, k8s_client):
    result = cli("create", 'namespace', 'cna-0006')
    assert result.returncode == 0, result.stderr
    assert "cna-0006" in result.stdout
    ns_names = {n.metadata.name for n in k8s_client.list_namespace().items}
    assert "cna-0006" in ns_names
