def test_create_deployment_0140_ok(cli):
    result = cli("create", 'deployment', 'cde-0140', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0140" in result.stdout
