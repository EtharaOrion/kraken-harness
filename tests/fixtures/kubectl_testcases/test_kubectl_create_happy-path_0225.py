def test_create_role_0225_ok(cli):
    result = cli("create", 'role', 'cro-0225', '--verb=get,list', '--resource=pods', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0225" in result.stdout
