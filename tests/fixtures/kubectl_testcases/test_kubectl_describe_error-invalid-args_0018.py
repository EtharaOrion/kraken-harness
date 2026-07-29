def test_describe_0018_invalid_flag(cli):
    result = cli("describe", "pods", "foo", '--openapi-print-columns=1')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err
