def test_get_clusterrole_0023_nonexistent(cli):
    result = cli("get", "clusterrole", "missing-clu-0023")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
