def test_describe_serviceaccount_0018_nonexistent(cli):
    result = cli("describe", "serviceaccount", "e404-ser-0018", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
