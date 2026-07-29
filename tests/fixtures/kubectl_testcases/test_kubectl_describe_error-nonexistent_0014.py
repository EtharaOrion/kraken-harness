def test_describe_ingress_0014_nonexistent(cli):
    result = cli("describe", "ingress", "e404-ing-0014", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
