def test_describe_limitrange_0021_nonexistent(cli):
    result = cli("describe", "limitrange", "e404-lim-0021", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
