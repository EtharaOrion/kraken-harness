def test_create_0019_invalid_flag(cli):
    result = cli("create", "configmap", "tmp", '--resource=')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err or "required" in err
