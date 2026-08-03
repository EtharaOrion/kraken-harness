def test_workflow_0295_configmap_full_lifecycle(cli, k8s_client, kubectl_bin):
    r_c = cli("create", "configmap", "wf-cm-0295", "--from-literal=k=v", "-n", "default")
    assert r_c.returncode == 0, r_c.stderr
    r_desc = cli("describe", "configmap", "wf-cm-0295", "-n", "default")
    assert r_desc.returncode == 0, r_desc.stderr
    r_patch = cli("patch", "configmap", "wf-cm-0295", "-n", "default", "-p", '{"data":{"extra":"e295"}}')
    assert r_patch.returncode == 0, r_patch.stderr
    r_label = cli("label", "configmap", "wf-cm-0295", "env=test", "-n", "default")
    assert r_label.returncode == 0, r_label.stderr
    r_del = cli("delete", "configmap", "wf-cm-0295", "-n", "default")
    assert r_del.returncode == 0, r_del.stderr
