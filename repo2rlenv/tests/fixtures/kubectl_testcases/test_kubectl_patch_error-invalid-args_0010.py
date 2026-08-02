def test_patch_0010_invalid_flag(cli):
    result = cli("patch", "pod", "foo", '--dry-run=maybe', "-p", '{"metadata":{"labels":{"a":"b"}}}')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err
