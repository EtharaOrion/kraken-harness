def test_delete_0006_invalid_flag(cli):
    result = cli("delete", "pod", "foo", '--cascade=maybe')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err
