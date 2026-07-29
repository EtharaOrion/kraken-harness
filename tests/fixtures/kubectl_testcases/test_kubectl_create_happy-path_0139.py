def test_create_deployment_0139_ok(cli):
    result = cli("create", 'deployment', 'cde-0139', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0139" in result.stdout
