def test_patch_networkpolicy_0023_nonexistent(cli):
    result = cli("patch", "networkpolicy", "p404-net-0023", "-n", "default", "-p", '{"metadata":{"labels":{"a":"b"}}}')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
