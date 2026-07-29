def test_scale_replicaset_0018_nonexistent(cli):
    result = cli("scale", "replicaset", "s404-rep-0018", "--replicas=1", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
