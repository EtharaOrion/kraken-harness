def test_create_namespace_0025_ok(cli, k8s_client):
    result = cli("create", 'namespace', 'cna-0025')
    assert result.returncode == 0, result.stderr
    assert "cna-0025" in result.stdout
    ns_names = {n.metadata.name for n in k8s_client.list_namespace().items}
    assert "cna-0025" in ns_names
