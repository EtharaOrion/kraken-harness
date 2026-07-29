def test_describe_configmap_0006_nonexistent(cli):
    result = cli("describe", "configmap", "e404-con-0006", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
