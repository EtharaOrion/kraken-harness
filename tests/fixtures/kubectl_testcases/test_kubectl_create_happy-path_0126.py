def test_create_deployment_0126_ok(cli):
    result = cli("create", 'deployment', 'cde-0126', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0126" in result.stdout
