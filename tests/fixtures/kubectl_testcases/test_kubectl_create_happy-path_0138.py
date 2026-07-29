def test_create_deployment_0138_ok(cli):
    result = cli("create", 'deployment', 'cde-0138', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0138" in result.stdout
