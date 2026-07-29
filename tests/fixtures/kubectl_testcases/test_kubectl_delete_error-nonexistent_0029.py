def test_delete_0029_ignore_not_found_returns_zero(cli):
    result = cli("delete", "pod", "inf-0029", "-n", "default", "--ignore-not-found")
    assert result.returncode == 0, result.stderr
