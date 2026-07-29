def test_workflow_create_configmap_get_describe_delete(cli, k8s_client, kubectl_bin):
    r_create = cli("create", "configmap", "wf04-cm", "--from-literal=key1=value1", "-n", "default")
    assert r_create.returncode == 0, r_create.stderr
    r_get = cli("get", "configmap", "wf04-cm", "-n", "default")
    assert r_get.returncode == 0, r_get.stderr
    assert "wf04-cm" in r_get.stdout
    r_desc = cli("describe", "configmap", "wf04-cm", "-n", "default")
    assert r_desc.returncode == 0, r_desc.stderr
    assert "key1" in r_desc.stdout
    r_del = cli("delete", "configmap", "wf04-cm", "-n", "default")
    assert r_del.returncode == 0, r_del.stderr
    r_get_gone = cli("get", "configmap", "wf04-cm", "-n", "default")
    assert r_get_gone.returncode == 1
    assert "not found" in r_get_gone.stderr.lower() or "notfound" in r_get_gone.stderr.lower()
