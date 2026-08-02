def test_describe_statefulset_0009_nonexistent(cli):
    result = cli("describe", "statefulset", "e404-sta-0009", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
