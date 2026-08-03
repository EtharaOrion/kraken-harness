def test_delete_0035_ignore_not_found_returns_zero(cli):
    result = cli("delete", "pod", "inf-0035", "-n", "default", "--ignore-not-found")
    assert result.returncode == 0, result.stderr
