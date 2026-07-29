def test_describe_cronjob_0013_nonexistent(cli):
    result = cli("describe", "cronjob", "e404-cro-0013", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
