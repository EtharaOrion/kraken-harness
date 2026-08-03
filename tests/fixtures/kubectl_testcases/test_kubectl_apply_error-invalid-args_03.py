def test_apply_nonexistent_file_returns_error(cli, tmp_path):
    result = cli("apply", "-f", str(tmp_path / "does-not-exist.yaml"))
    assert result.returncode == 1
    stderr = result.stderr.lower()
    assert "no such file" in stderr or "not exist" in stderr
