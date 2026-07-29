def test_get_pods_0016_invalid_flag(cli):
    result = cli("get", "pods", '-o=jsonpath')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err or "required" in err
