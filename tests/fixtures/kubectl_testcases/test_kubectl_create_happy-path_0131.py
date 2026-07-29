def test_create_deployment_0131_ok(cli):
    result = cli("create", 'deployment', 'cde-0131', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0131" in result.stdout
