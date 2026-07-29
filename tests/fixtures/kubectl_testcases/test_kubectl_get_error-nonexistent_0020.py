def test_get_resourcequota_0020_nonexistent(cli):
    result = cli("get", "resourcequota", "missing-res-0020", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
