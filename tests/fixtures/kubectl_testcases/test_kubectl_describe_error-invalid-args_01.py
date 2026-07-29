def test_describe_invalid_flag(cli):
    result = cli("describe", "pods", "some-resource", "--invalid-flag")
    assert result.returncode == 1
    assert "unknown" in result.stderr.lower() or "invalid" in result.stderr.lower()
