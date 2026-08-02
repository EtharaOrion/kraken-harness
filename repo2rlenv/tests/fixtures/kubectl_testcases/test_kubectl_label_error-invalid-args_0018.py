def test_label_0018_invalid_flag(cli):
    result = cli("label", "pod", "foo", "k=v", '--field-manager=')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err
