def test_describe_selector_and_name_conflict(cli):
    result = cli("describe", "pod", "some-pod", "-l", "app=x", "-n", "default")
    assert result.returncode == 1
    stderr = result.stderr.lower()
    assert "cannot" in stderr or "conflict" in stderr or "selector" in stderr or "not found" in stderr
