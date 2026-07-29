def test_scale_statefulset_0017_nonexistent(cli):
    result = cli("scale", "statefulset", "s404-sta-0017", "--replicas=1", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
