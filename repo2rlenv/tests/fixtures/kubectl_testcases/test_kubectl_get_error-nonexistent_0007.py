def test_get_secret_0007_nonexistent(cli):
    result = cli("get", "secret", "missing-sec-0007", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
