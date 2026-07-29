def test_get_rolebinding_0017_nonexistent(cli):
    result = cli("get", "rolebinding", "missing-rol-0017", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
