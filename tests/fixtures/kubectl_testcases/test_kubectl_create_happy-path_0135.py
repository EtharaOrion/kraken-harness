def test_create_deployment_0135_ok(cli):
    result = cli("create", 'deployment', 'cde-0135', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0135" in result.stdout
