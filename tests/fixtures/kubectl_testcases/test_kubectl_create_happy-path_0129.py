def test_create_deployment_0129_ok(cli):
    result = cli("create", 'deployment', 'cde-0129', '--image=nginx', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cde-0129" in result.stdout
