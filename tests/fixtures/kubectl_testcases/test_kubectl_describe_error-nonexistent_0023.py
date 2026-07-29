def test_describe_clusterrole_0023_nonexistent(cli):
    result = cli("describe", "clusterrole", "e404-clu-0023")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
