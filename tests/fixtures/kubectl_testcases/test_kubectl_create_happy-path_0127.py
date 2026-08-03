def test_create_deployment_0127_ok(cli):
    result = cli("create", 'deployment', 'cde-0127', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0127" in result.stdout
