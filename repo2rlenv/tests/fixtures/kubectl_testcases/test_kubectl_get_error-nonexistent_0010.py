def test_get_daemonset_0010_nonexistent(cli):
    result = cli("get", "daemonset", "missing-dae-0010", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
