def test_label_cronjob_0013_nonexistent(cli):
    result = cli("label", "cronjob", "l404-cro-0013", "k=v", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
