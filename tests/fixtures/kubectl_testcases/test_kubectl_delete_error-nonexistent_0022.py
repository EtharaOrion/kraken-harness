def test_delete_namespace_0022_nonexistent(cli):
    result = cli("delete", "namespace", "gone-nam-0022")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
