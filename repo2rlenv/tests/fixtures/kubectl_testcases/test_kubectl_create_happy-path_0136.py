def test_create_deployment_0136_ok(cli):
    result = cli("create", 'deployment', 'cde-0136', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0136" in result.stdout
