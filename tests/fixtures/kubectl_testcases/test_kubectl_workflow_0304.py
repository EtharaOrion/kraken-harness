def test_workflow_0304_configmap_full_lifecycle(cli, k8s_client, kubectl_bin):
    r_c = cli("create", "configmap", "wf-cm-0304", "--from-literal=k=v", "-n", "default")
    assert r_c.returncode == 0, r_c.stderr
    r_desc = cli("describe", "configmap", "wf-cm-0304", "-n", "default")
    assert r_desc.returncode == 0, r_desc.stderr
    r_patch = cli("patch", "configmap", "wf-cm-0304", "-n", "default", "-p", '{"data":{"extra":"e304"}}')
    assert r_patch.returncode == 0, r_patch.stderr
    r_label = cli("label", "configmap", "wf-cm-0304", "env=test", "-n", "default")
    assert r_label.returncode == 0, r_label.stderr
    r_del = cli("delete", "configmap", "wf-cm-0304", "-n", "default")
    assert r_del.returncode == 0, r_del.stderr
