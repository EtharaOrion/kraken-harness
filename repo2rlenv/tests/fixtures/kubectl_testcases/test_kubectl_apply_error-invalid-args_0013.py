def test_apply_0013_invalid_flag(cli):
    result = cli("apply", '--filename=/tmp/does-not-exist-99999.yaml')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err or "required" in err
