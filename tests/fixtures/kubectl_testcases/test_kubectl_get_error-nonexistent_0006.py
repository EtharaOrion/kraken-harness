def test_get_configmap_0006_nonexistent(cli):
    result = cli("get", "configmap", "missing-con-0006", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
