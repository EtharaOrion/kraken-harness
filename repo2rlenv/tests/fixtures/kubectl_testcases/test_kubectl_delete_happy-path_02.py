def test_delete_namespace_removes_resource(cli, k8s_client, kubectl_bin):
    ns_name = "del-ns-hp02"
    seed = kubectl_bin(["create", "namespace", ns_name])
    assert seed.returncode == 0, seed.stderr
    result = cli("delete", "namespace", ns_name)
    assert result.returncode == 0, result.stderr
    assert f"namespace/{ns_name}" in result.stdout
    assert "deleted" in result.stdout.lower()
    ns_names = {n.metadata.name for n in k8s_client.list_namespace().items}
    assert ns_name not in ns_names
