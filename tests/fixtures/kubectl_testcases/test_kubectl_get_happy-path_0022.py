def test_get_namespace_0022_by_name(cli, k8s_client, kubectl_bin):
    seed = kubectl_bin(["create", "namespace", "gna-0022"])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "namespace", "gna-0022")
    assert result.returncode == 0, result.stderr
    assert "gna-0022" in result.stdout
    ns_names = {n.metadata.name for n in k8s_client.list_namespace().items}
    assert "gna-0022" in ns_names
