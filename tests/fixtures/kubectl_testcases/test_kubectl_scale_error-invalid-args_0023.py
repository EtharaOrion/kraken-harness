def test_scale_0023_invalid_flag(cli):
    result = cli("scale", "deployment", "foo", '--filename=/no/such/file')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err or "required" in err
