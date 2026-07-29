def test_delete_cronjob_0013_nonexistent(cli):
    result = cli("delete", "cronjob", "gone-cro-0013", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
