def test_label_namespace_0022_nonexistent(cli):
    result = cli("label", "namespace", "l404-nam-0022", "k=v")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
