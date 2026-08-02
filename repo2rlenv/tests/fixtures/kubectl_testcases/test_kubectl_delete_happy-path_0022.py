def test_delete_namespace_0022_by_name(cli, k8s_client, kubectl_bin):
    seed = kubectl_bin(["create", "namespace", "dna-0022"])
    assert seed.returncode == 0, seed.stderr
    result = cli("delete", "namespace", "dna-0022")
    assert result.returncode == 0, result.stderr
    ns_names = {n.metadata.name for n in k8s_client.list_namespace().items}
    assert "dna-0022" not in ns_names
