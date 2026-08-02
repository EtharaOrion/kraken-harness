def test_scale_statefulset_0013_nonexistent(cli):
    result = cli("scale", "statefulset", "s404-sta-0013", "--replicas=1", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
