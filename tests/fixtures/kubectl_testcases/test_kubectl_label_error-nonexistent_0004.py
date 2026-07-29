def test_label_pod_0004_nonexistent(cli):
    result = cli("label", "pod", "l404-pod-0004", "k=v", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
