def test_label_networkpolicy_0015_nonexistent(cli):
    result = cli("label", "networkpolicy", "l404-net-0015", "k=v", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
