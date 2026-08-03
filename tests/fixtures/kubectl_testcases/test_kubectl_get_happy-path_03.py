def test_get_namespace_by_name_returns_it(cli, k8s_client, kubectl_bin):
    ns_name = "get-ns-hp03"
    seed = kubectl_bin(["create", "namespace", ns_name])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "namespace", ns_name)
    assert result.returncode == 0, result.stderr
    assert ns_name in result.stdout
    ns_names = {n.metadata.name for n in k8s_client.list_namespace().items}
    assert ns_name in ns_names
