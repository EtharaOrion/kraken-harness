def test_create_deployment_0130_ok(cli):
    result = cli("create", 'deployment', 'cde-0130', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0130" in result.stdout
