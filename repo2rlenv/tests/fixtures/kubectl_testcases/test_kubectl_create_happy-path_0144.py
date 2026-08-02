def test_create_deployment_0144_ok(cli):
    result = cli("create", 'deployment', 'cde-0144', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0144" in result.stdout
