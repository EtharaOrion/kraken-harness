def test_create_deployment_0132_ok(cli):
    result = cli("create", 'deployment', 'cde-0132', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0132" in result.stdout
