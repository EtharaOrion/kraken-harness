def test_label_missing_label_arg_returns_error(cli):
    result = cli("label", "pod", "some-pod", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "labels" in err or "required" in err or "at least one" in err or "usage" in err
