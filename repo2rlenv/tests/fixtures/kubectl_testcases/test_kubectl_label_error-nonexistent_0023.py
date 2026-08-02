def test_label_clusterrole_0023_nonexistent(cli):
    result = cli("label", "clusterrole", "l404-clu-0023", "k=v")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
