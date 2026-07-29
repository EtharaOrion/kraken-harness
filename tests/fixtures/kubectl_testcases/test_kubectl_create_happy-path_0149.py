def test_create_deployment_0149_ok(cli):
    result = cli("create", 'deployment', 'cde-0149', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0149" in result.stdout
