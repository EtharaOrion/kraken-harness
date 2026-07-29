def test_describe_pod_0004_nonexistent(cli):
    result = cli("describe", "pod", "e404-pod-0004", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
