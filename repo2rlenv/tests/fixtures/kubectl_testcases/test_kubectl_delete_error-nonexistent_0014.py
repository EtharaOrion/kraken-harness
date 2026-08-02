def test_delete_ingress_0014_nonexistent(cli):
    result = cli("delete", "ingress", "gone-ing-0014", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
