def test_workflow_create_get_describe_delete_namespace(cli, k8s_client, kubectl_bin):
    r_create = cli("create", "namespace", "wf01-ns")
    assert r_create.returncode == 0, r_create.stderr
    r_get = cli("get", "namespace", "wf01-ns")
    assert r_get.returncode == 0, r_get.stderr
    assert "wf01-ns" in r_get.stdout
    r_desc = cli("describe", "namespace", "wf01-ns")
    assert r_desc.returncode == 0, r_desc.stderr
    assert "wf01-ns" in r_desc.stdout
    ns_names = {n.metadata.name for n in k8s_client.list_namespace().items}
    assert "wf01-ns" in ns_names
    r_del = cli("delete", "namespace", "wf01-ns")
    assert r_del.returncode == 0, r_del.stderr
    r_get_gone = cli("get", "namespace", "wf01-ns")
    assert r_get_gone.returncode == 1
    assert "not found" in r_get_gone.stderr.lower() or "notfound" in r_get_gone.stderr.lower()
