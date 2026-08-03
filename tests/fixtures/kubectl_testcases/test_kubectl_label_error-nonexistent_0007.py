def test_label_secret_0007_nonexistent(cli):
    result = cli("label", "secret", "l404-sec-0007", "k=v", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
