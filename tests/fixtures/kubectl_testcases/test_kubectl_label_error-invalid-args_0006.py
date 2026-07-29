def test_label_0006_invalid_flag(cli):
    result = cli("label", "pod", "foo", "k=v", '--resource-version=')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err
