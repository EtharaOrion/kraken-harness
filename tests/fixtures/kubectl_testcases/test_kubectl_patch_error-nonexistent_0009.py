def test_patch_statefulset_0009_nonexistent(cli):
    result = cli("patch", "statefulset", "p404-sta-0009", "-n", "default", "-p", '{"metadata":{"labels":{"a":"b"}}}')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
