def test_patch_rolebinding_0018_nonexistent(cli):
    result = cli("patch", "rolebinding", "p404-rol-0018", "-n", "default", "-p", '{"metadata":{"labels":{"a":"b"}}}')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
