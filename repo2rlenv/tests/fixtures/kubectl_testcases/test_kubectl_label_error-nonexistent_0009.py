def test_label_statefulset_0009_nonexistent(cli):
    result = cli("label", "statefulset", "l404-sta-0009", "k=v", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
