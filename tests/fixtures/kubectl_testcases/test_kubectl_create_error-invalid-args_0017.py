def test_create_0017_invalid_flag(cli):
    result = cli("create", "configmap", "tmp", '--tcp=badformat')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err or "required" in err
