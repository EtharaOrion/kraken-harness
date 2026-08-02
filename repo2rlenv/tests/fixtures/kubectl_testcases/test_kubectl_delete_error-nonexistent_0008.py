def test_delete_deployment_0008_nonexistent(cli):
    result = cli("delete", "deployment", "gone-dep-0008", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
