def test_create_deployment_0148_ok(cli):
    result = cli("create", 'deployment', 'cde-0148', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0148" in result.stdout
