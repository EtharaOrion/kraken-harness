def test_describe_persistentvolumeclaim_0019_nonexistent(cli):
    result = cli("describe", "persistentvolumeclaim", "e404-per-0019", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
