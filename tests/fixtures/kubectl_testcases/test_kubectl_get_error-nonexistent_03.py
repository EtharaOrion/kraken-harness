def test_get_deployment_nonexistent_returns_notfound(cli):
    result = cli("get", "deployment", "nonexistent-get-ne03", "-n", "default")
    assert result.returncode == 1
    assert "not found" in result.stderr.lower() or "notfound" in result.stderr.lower()
