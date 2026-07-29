def test_workflow_0327_secret_patch_delete(cli, kubectl_bin, k8s_client):
    r_c = cli("create", "secret", "generic", "wf-sec-0327", "--from-literal=t=x", "-n", "default")
    assert r_c.returncode == 0, r_c.stderr
    r_get = cli("get", "secret", "wf-sec-0327", "-n", "default")
    assert r_get.returncode == 0, r_get.stderr
    r_patch = cli("patch", "secret", "wf-sec-0327", "-n", "default", "-p", '{"metadata":{"annotations":{"team":"sec327"}}}')
    assert r_patch.returncode == 0, r_patch.stderr
    r_del = cli("delete", "secret", "wf-sec-0327", "-n", "default")
    assert r_del.returncode == 0, r_del.stderr
    r_gone = cli("get", "secret", "wf-sec-0327", "-n", "default")
    assert r_gone.returncode == 1
    err = r_gone.stderr.lower()
    assert "not found" in err or "notfound" in err
