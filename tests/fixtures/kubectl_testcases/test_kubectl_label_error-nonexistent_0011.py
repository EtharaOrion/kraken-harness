def test_label_replicaset_0011_nonexistent(cli):
    result = cli("label", "replicaset", "l404-rep-0011", "k=v", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
