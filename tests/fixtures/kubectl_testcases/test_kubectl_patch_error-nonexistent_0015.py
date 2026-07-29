def test_patch_namespace_0015_nonexistent(cli):
    result = cli("patch", "namespace", "p404-nam-0015", "-p", '{"metadata":{"labels":{"a":"b"}}}')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
