def test_get_pods_0015_invalid_flag(cli):
    result = cli("get", "pods", '-l=')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err or "required" in err
