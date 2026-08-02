def test_delete_nonexistent_namespace_returns_notfound(cli):
    result = cli("delete", "namespace", "nonexistent-del-ne03")
    assert result.returncode == 1
    stderr = result.stderr.lower()
    assert "not found" in stderr or "notfound" in stderr
