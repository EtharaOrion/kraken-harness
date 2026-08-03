def test_workflow_create_secret_get_describe_delete(cli, k8s_client, kubectl_bin):
    r_create = cli(
        "create", "secret", "generic", "wf09-secret",
        "--from-literal=token=s3cret",
        "-n", "default",
    )
    assert r_create.returncode == 0, r_create.stderr
    r_get = cli("get", "secret", "wf09-secret", "-n", "default")
    assert r_get.returncode == 0, r_get.stderr
    assert "wf09-secret" in r_get.stdout
    r_desc = cli("describe", "secret", "wf09-secret", "-n", "default")
    assert r_desc.returncode == 0, r_desc.stderr
    assert "token" in r_desc.stdout
    r_del = cli("delete", "secret", "wf09-secret", "-n", "default")
    assert r_del.returncode == 0, r_del.stderr
    r_get_gone = cli("get", "secret", "wf09-secret", "-n", "default")
    assert r_get_gone.returncode == 1
    assert "not found" in r_get_gone.stderr.lower() or "notfound" in r_get_gone.stderr.lower()
