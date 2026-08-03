def test_label_invalid_flag_returns_error(cli):
    result = cli("label", "pod", "some-pod", "--invalid-flag", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err
