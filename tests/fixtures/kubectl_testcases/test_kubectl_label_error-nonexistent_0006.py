def test_label_configmap_0006_nonexistent(cli):
    result = cli("label", "configmap", "l404-con-0006", "k=v", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
