def test_label_role_0016_nonexistent(cli):
    result = cli("label", "role", "l404-rol-0016", "k=v", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
