def test_label_resourcequota_0020_nonexistent(cli):
    result = cli("label", "resourcequota", "l404-res-0020", "k=v", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
