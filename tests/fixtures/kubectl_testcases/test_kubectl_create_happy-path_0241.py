def test_create_role_0241_ok(cli):
    result = cli("create", 'role', 'cro-0241', '--verb=get,list', '--resource=pods', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0241" in result.stdout
