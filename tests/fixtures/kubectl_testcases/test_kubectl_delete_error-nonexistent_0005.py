def test_delete_service_0005_nonexistent(cli):
    result = cli("delete", "service", "gone-ser-0005", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
