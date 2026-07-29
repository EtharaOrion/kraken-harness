def test_get_invalid_flag(cli):
    result = cli("get", "pods", "--invalid-flag")
    assert result.returncode == 1
    assert "unknown" in result.stderr.lower() or "invalid" in result.stderr.lower()
