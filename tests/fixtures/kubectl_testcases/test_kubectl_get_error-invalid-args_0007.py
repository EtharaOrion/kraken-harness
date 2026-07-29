def test_get_pods_0007_invalid_flag(cli):
    result = cli("get", "pods", '-n')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err or "required" in err
