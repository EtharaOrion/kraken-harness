def test_apply_0020_invalid_flag(cli):
    result = cli("apply", '--grace-period=-2')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err or "required" in err
