def test_delete_serviceaccount_0018_nonexistent(cli):
    result = cli("delete", "serviceaccount", "gone-ser-0018", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
