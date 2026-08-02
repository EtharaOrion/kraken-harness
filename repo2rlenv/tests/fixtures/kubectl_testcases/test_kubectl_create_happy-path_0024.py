def test_create_namespace_0024_ok(cli, k8s_client):
    result = cli("create", 'namespace', 'cna-0024')
    assert result.returncode == 0, result.stderr
    assert "cna-0024" in result.stdout
    ns_names = {n.metadata.name for n in k8s_client.list_namespace().items}
    assert "cna-0024" in ns_names
