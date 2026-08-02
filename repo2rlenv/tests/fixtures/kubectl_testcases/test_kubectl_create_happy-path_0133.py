def test_create_deployment_0133_ok(cli):
    result = cli("create", 'deployment', 'cde-0133', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0133" in result.stdout
