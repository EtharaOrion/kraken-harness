def test_scale_0019_invalid_flag(cli):
    result = cli("scale", "deployment", "foo", '--username=')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err or "required" in err
