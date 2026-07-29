def test_delete_clusterrole_0023_nonexistent(cli):
    result = cli("delete", "clusterrole", "gone-clu-0023")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
