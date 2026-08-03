def test_label_malformed_label_spec_returns_error(cli):
    result = cli("label", "pod", "some-pod", "-n", "default", "bad label spec with spaces")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "invalid" in err or "label" in err or "unable" in err or "format" in err
