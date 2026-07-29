def test_describe_0019_invalid_flag(cli):
    result = cli("describe", "pods", "foo", '-o=whatever')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err
