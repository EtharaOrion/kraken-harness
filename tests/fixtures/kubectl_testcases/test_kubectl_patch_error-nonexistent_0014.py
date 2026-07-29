def test_patch_ingress_0014_nonexistent(cli):
    result = cli("patch", "ingress", "p404-ing-0014", "-n", "default", "-p", '{"metadata":{"labels":{"a":"b"}}}')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
