def test_create_role_0236_ok(cli):
    result = cli("create", 'role', 'cro-0236', '--verb=get,list', '--resource=pods', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0236" in result.stdout
