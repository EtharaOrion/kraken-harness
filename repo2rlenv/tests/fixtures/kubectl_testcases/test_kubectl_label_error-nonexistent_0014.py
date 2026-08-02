def test_label_ingress_0014_nonexistent(cli):
    result = cli("label", "ingress", "l404-ing-0014", "k=v", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
