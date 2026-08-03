def test_apply_0020_nonexistent_file(cli, tmp_path):
    missing = tmp_path / "missing-0020.yaml"
    result = cli("apply", "-f", str(missing))
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "no such file" in err or "not found" in err or "error" in err
