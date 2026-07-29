def test_create_deployment_0145_ok(cli):
    result = cli("create", 'deployment', 'cde-0145', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0145" in result.stdout
