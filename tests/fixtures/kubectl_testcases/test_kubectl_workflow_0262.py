def test_workflow_0262_configmap_full_lifecycle(cli, k8s_client, kubectl_bin):
    r_c = cli("create", "configmap", "wf-cm-0262", "--from-literal=k=v", "-n", "default")
    assert r_c.returncode == 0, r_c.stderr
    r_desc = cli("describe", "configmap", "wf-cm-0262", "-n", "default")
    assert r_desc.returncode == 0, r_desc.stderr
    r_patch = cli("patch", "configmap", "wf-cm-0262", "-n", "default", "-p", '{"data":{"extra":"e262"}}')
    assert r_patch.returncode == 0, r_patch.stderr
    r_label = cli("label", "configmap", "wf-cm-0262", "env=test", "-n", "default")
    assert r_label.returncode == 0, r_label.stderr
    r_del = cli("delete", "configmap", "wf-cm-0262", "-n", "default")
    assert r_del.returncode == 0, r_del.stderr
