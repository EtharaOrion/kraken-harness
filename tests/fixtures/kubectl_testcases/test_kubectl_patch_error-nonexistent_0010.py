def test_patch_daemonset_0010_nonexistent(cli):
    result = cli("patch", "daemonset", "p404-dae-0010", "-n", "default", "-p", '{"metadata":{"labels":{"a":"b"}}}')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
