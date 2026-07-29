def test_patch_pod_0004_nonexistent(cli):
    result = cli("patch", "pod", "p404-pod-0004", "-n", "default", "-p", '{"metadata":{"labels":{"a":"b"}}}')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
