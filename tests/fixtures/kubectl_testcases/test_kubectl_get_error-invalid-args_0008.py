def test_get_pods_0008_invalid_flag(cli):
    result = cli("get", "pods", '--sort-by=@@@')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err or "required" in err
