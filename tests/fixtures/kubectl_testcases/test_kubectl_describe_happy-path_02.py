def test_describe_namespace_shows_details(cli, k8s_client, kubectl_bin):
    ns_name = "desc-ns-hp02"
    seed = kubectl_bin(["create", "namespace", ns_name])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "namespace", ns_name)
    assert result.returncode == 0, result.stderr
    assert ns_name in result.stdout
    assert "Name:" in result.stdout
    assert "Status:" in result.stdout
    ns_names = {n.metadata.name for n in k8s_client.list_namespace().items}
    assert ns_name in ns_names
