def test_patch_deployment_0008_nonexistent(cli):
    result = cli("patch", "deployment", "p404-dep-0008", "-n", "default", "-p", '{"metadata":{"labels":{"a":"b"}}}')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
