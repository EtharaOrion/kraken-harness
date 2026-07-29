def test_delete_pod_0004_nonexistent(cli):
    result = cli("delete", "pod", "gone-pod-0004", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
