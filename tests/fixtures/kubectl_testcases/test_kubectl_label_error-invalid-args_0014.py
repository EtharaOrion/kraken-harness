def test_label_0014_invalid_flag(cli):
    result = cli("label", "pod", "foo", "k=v", '--username=')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err
