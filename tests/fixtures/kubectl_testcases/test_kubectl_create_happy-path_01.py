def test_create_namespace_succeeds(cli, k8s_client, kubectl_bin, tmp_path):
    ns_name = f"ns-cr-hp01-{tmp_path.name.replace('_', '-').lower()[:30]}"
    result = cli("create", "namespace", ns_name)
    assert result.returncode == 0, result.stderr
    assert f"namespace/{ns_name} created" in result.stdout
    namespaces = k8s_client.list_namespace().items
    assert any(n.metadata.name == ns_name for n in namespaces)
