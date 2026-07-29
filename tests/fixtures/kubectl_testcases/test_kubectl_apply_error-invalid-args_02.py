def test_apply_missing_filename_returns_error(cli):
    result = cli("apply")
    assert result.returncode == 1
    stderr = result.stderr.lower()
    assert "required" in stderr or "filename" in stderr or "-f" in stderr or "must specify" in stderr
