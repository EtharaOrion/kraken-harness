def test_get_role_0016_nonexistent(cli):
    result = cli("get", "role", "missing-rol-0016", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
