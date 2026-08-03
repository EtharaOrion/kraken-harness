def test_scale_replicationcontroller_0019_nonexistent(cli):
    result = cli("scale", "replicationcontroller", "s404-rep-0019", "--replicas=1", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
