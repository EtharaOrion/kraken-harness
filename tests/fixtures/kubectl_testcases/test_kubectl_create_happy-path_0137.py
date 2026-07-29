def test_create_deployment_0137_ok(cli):
    result = cli("create", 'deployment', 'cde-0137', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0137" in result.stdout
