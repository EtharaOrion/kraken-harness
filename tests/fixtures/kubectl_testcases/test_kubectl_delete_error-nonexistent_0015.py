def test_delete_networkpolicy_0015_nonexistent(cli):
    result = cli("delete", "networkpolicy", "gone-net-0015", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
