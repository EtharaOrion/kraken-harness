def test_label_0008_invalid_flag(cli):
    result = cli("label", "pod", "foo", "k=v", '-o=badformat')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err
