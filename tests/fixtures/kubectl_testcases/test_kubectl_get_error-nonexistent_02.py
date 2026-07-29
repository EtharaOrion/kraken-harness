def test_get_namespace_nonexistent_returns_notfound(cli, k8s_client):
    result = cli("get", "namespace", "nonexistent-get-ne02")
    assert result.returncode == 1
    assert "not found" in result.stderr.lower() or "notfound" in result.stderr.lower()
    ns_names = {n.metadata.name for n in k8s_client.list_namespace().items}
    assert "nonexistent-get-ne02" not in ns_names
