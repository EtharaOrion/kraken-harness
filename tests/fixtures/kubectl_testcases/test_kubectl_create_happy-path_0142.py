def test_create_deployment_0142_ok(cli):
    result = cli("create", 'deployment', 'cde-0142', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0142" in result.stdout
