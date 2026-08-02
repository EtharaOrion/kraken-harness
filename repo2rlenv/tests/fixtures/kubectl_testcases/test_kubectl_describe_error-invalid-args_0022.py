def test_describe_0022_invalid_flag(cli):
    result = cli("describe", "pods", "foo", '--field-manager=')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err
