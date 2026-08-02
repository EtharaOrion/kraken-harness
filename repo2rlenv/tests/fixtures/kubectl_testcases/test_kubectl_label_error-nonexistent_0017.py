def test_label_rolebinding_0017_nonexistent(cli):
    result = cli("label", "rolebinding", "l404-rol-0017", "k=v", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
