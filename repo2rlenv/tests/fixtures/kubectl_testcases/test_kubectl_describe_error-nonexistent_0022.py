def test_describe_namespace_0022_nonexistent(cli):
    result = cli("describe", "namespace", "e404-nam-0022")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
