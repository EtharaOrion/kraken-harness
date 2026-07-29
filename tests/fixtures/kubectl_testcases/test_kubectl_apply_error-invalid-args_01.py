def test_apply_invalid_flag_returns_error(cli):
    result = cli("apply", "--invalid-flag")
    assert result.returncode == 1
    assert "unknown" in result.stderr.lower() or "invalid" in result.stderr.lower()
