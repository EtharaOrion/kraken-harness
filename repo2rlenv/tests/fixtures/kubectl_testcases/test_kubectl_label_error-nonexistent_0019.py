def test_label_persistentvolumeclaim_0019_nonexistent(cli):
    result = cli("label", "persistentvolumeclaim", "l404-per-0019", "k=v", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
