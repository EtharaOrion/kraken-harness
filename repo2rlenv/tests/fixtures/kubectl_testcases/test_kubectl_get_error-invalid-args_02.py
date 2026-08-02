def test_get_bad_output_format(cli):
    result = cli("get", "pods", "-o", "badformat")
    assert result.returncode == 1
    stderr = result.stderr.lower()
    assert "output" in stderr or "format" in stderr or "unable" in stderr
