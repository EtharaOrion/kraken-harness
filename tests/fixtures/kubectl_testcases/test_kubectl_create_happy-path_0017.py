def test_create_namespace_0017_ok(cli, k8s_client):
    result = cli("create", 'namespace', 'cna-0017')
    assert result.returncode == 0, result.stderr
    assert "cna-0017" in result.stdout
    ns_names = {n.metadata.name for n in k8s_client.list_namespace().items}
    assert "cna-0017" in ns_names
