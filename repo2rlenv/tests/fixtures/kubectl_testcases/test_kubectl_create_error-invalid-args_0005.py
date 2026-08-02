def test_create_0005_invalid_flag(cli):
    result = cli("create", "configmap", "tmp", '--dry-run=maybe')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err or "required" in err
