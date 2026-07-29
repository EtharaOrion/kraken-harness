def test_patch_service_0005_nonexistent(cli):
    result = cli("patch", "service", "p404-ser-0005", "-n", "default", "-p", '{"metadata":{"labels":{"a":"b"}}}')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
