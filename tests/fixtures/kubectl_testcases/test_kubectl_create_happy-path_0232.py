def test_create_role_0232_ok(cli):
    result = cli("create", 'role', 'cro-0232', '--verb=get,list', '--resource=pods', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0232" in result.stdout
