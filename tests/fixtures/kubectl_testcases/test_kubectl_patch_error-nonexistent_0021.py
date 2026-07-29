def test_patch_resourcequota_0021_nonexistent(cli):
    result = cli("patch", "resourcequota", "p404-res-0021", "-n", "default", "-p", '{"metadata":{"labels":{"a":"b"}}}')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
