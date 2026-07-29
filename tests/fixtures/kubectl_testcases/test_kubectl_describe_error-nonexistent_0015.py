def test_describe_networkpolicy_0015_nonexistent(cli):
    result = cli("describe", "networkpolicy", "e404-net-0015", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
