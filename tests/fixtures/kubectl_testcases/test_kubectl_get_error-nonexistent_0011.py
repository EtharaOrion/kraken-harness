def test_get_replicaset_0011_nonexistent(cli):
    result = cli("get", "replicaset", "missing-rep-0011", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
