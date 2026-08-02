def test_label_limitrange_0021_nonexistent(cli):
    result = cli("label", "limitrange", "l404-lim-0021", "k=v", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
