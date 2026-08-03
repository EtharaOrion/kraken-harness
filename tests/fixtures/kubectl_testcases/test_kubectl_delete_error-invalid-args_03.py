def test_delete_missing_resource_returns_error(cli):
    result = cli("delete")
    assert result.returncode == 1
    stderr = result.stderr.lower()
    assert "required" in stderr or "resource" in stderr or "you must" in stderr or "usage" in stderr
