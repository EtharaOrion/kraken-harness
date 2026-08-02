def test_scale_deployment_0008_nonexistent(cli):
    result = cli("scale", "deployment", "s404-dep-0008", "--replicas=1", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
