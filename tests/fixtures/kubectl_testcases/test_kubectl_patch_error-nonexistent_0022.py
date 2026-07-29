def test_patch_limitrange_0022_nonexistent(cli):
    result = cli("patch", "limitrange", "p404-lim-0022", "-n", "default", "-p", '{"metadata":{"labels":{"a":"b"}}}')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
