def test_delete_unknown_flag_returns_error(cli):
    result = cli("delete", "pod", "some-pod", "--invalid-flag")
    assert result.returncode == 1
    stderr = result.stderr.lower()
    assert "unknown" in stderr or "invalid" in stderr
