def test_get_cronjob_0013_nonexistent(cli):
    result = cli("get", "cronjob", "missing-cro-0013", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
