def test_create_deployment_0128_ok(cli):
    result = cli("create", 'deployment', 'cde-0128', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0128" in result.stdout
