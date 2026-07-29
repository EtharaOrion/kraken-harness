def test_scale_0012_invalid_flag(cli):
    result = cli("scale", "deployment", "foo", '--dry-run=maybe')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err or "required" in err
