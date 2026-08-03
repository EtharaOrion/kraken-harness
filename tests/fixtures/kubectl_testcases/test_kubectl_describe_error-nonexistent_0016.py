def test_describe_role_0016_nonexistent(cli):
    result = cli("describe", "role", "e404-rol-0016", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
