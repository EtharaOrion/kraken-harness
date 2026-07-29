def test_create_deployment_0143_ok(cli):
    result = cli("create", 'deployment', 'cde-0143', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0143" in result.stdout
