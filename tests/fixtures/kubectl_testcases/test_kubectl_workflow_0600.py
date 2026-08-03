def test_workflow_0600_rbac_lifecycle(cli, kubectl_bin):
    r1 = cli("create", "serviceaccount", "wf-sa-0600", "-n", "default")
    assert r1.returncode == 0, r1.stderr
    r2 = cli("create", "role", "wf-rl-0600", "--verb=get,list", "--resource=pods", "-n", "default")
    assert r2.returncode == 0, r2.stderr
    r3 = cli("create", "rolebinding", "wf-rb-0600", "--role=wf-rl-0600", "--serviceaccount=default:wf-sa-0600", "-n", "default")
    assert r3.returncode == 0, r3.stderr
    d1 = cli("delete", "rolebinding", "wf-rb-0600", "-n", "default")
    assert d1.returncode == 0, d1.stderr
    d2 = cli("delete", "role", "wf-rl-0600", "-n", "default")
    assert d2.returncode == 0, d2.stderr
    d3 = cli("delete", "serviceaccount", "wf-sa-0600", "-n", "default")
    assert d3.returncode == 0, d3.stderr
