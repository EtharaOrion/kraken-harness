def test_patch_secret_0007_nonexistent(cli):
    result = cli("patch", "secret", "p404-sec-0007", "-n", "default", "-p", '{"metadata":{"labels":{"a":"b"}}}')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
