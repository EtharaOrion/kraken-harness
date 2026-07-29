def test_create_deployment_0134_ok(cli):
    result = cli("create", 'deployment', 'cde-0134', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0134" in result.stdout
