def test_patch_serviceaccount_0019_nonexistent(cli):
    result = cli("patch", "serviceaccount", "p404-ser-0019", "-n", "default", "-p", '{"metadata":{"labels":{"a":"b"}}}')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
