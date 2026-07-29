def test_patch_clusterrole_0016_nonexistent(cli):
    result = cli("patch", "clusterrole", "p404-clu-0016", "-p", '{"metadata":{"labels":{"a":"b"}}}')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
