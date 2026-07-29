def test_create_deployment_0146_ok(cli):
    result = cli("create", 'deployment', 'cde-0146', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0146" in result.stdout
