def test_describe_service_0005_nonexistent(cli):
    result = cli("describe", "service", "e404-ser-0005", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
