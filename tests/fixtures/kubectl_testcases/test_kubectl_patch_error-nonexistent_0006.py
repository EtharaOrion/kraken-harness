def test_patch_configmap_0006_nonexistent(cli):
    result = cli("patch", "configmap", "p404-con-0006", "-n", "default", "-p", '{"metadata":{"labels":{"a":"b"}}}')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
