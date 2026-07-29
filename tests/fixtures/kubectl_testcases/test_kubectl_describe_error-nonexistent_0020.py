def test_describe_resourcequota_0020_nonexistent(cli):
    result = cli("describe", "resourcequota", "e404-res-0020", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
