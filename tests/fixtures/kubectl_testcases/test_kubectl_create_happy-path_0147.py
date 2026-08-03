def test_create_deployment_0147_ok(cli):
    result = cli("create", 'deployment', 'cde-0147', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0147" in result.stdout
