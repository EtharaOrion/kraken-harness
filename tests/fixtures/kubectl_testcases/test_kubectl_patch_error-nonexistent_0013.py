def test_patch_cronjob_0013_nonexistent(cli):
    result = cli("patch", "cronjob", "p404-cro-0013", "-n", "default", "-p", '{"metadata":{"labels":{"a":"b"}}}')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
