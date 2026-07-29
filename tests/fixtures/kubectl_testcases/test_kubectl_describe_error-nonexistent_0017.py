def test_describe_rolebinding_0017_nonexistent(cli):
    result = cli("describe", "rolebinding", "e404-rol-0017", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
