def test_delete_replicaset_0011_nonexistent(cli):
    result = cli("delete", "replicaset", "gone-rep-0011", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
