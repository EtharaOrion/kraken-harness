def test_delete_persistentvolumeclaim_0019_nonexistent(cli):
    result = cli("delete", "persistentvolumeclaim", "gone-per-0019", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
