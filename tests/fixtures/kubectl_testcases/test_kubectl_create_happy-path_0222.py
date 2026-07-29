def test_create_role_0222_ok(cli):
    result = cli("create", 'role', 'cro-0222', '--verb=get,list', '--resource=pods', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0222" in result.stdout
