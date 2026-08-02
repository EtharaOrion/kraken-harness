def test_patch_role_0017_nonexistent(cli):
    result = cli("patch", "role", "p404-rol-0017", "-n", "default", "-p", '{"metadata":{"labels":{"a":"b"}}}')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
