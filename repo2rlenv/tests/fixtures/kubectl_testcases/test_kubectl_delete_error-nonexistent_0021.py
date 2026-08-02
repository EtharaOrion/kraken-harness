def test_delete_limitrange_0021_nonexistent(cli):
    result = cli("delete", "limitrange", "gone-lim-0021", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
