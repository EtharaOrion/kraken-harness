def test_patch_replicaset_0011_nonexistent(cli):
    result = cli("patch", "replicaset", "p404-rep-0011", "-n", "default", "-p", '{"metadata":{"labels":{"a":"b"}}}')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
