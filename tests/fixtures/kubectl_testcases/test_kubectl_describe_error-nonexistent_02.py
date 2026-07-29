def test_describe_deployment_nonexistent_returns_notfound(cli):
    result = cli("describe", "deployment", "nonexistent-desc-ne02", "-n", "default")
    assert result.returncode == 1
    assert "not found" in result.stderr.lower() or "notfound" in result.stderr.lower()
