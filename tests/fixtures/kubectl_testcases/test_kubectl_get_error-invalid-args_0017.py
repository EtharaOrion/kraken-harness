def test_get_pods_0017_invalid_flag(cli):
    result = cli("get", "pods", '--filename=/nonexistent/path.yaml')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err or "required" in err
