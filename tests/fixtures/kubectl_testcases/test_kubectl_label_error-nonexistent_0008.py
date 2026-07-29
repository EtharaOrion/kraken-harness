def test_label_deployment_0008_nonexistent(cli):
    result = cli("label", "deployment", "l404-dep-0008", "k=v", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
