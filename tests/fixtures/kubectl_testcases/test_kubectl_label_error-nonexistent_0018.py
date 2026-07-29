def test_label_serviceaccount_0018_nonexistent(cli):
    result = cli("label", "serviceaccount", "l404-ser-0018", "k=v", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
