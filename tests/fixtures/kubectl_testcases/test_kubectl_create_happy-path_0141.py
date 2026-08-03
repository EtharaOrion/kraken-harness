def test_create_deployment_0141_ok(cli):
    result = cli("create", 'deployment', 'cde-0141', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0141" in result.stdout
