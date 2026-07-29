def test_delete_nonexistent_pod_ignore_not_found_succeeds(cli):
    result = cli("delete", "pod", "nonexistent-del-ne02", "--ignore-not-found", "-n", "default")
    assert result.returncode == 0, result.stderr
