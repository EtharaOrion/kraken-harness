def test_label_daemonset_0010_nonexistent(cli):
    result = cli("label", "daemonset", "l404-dae-0010", "k=v", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
