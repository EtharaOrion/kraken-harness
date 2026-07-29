def test_create_role_0224_ok(cli):
    result = cli("create", 'role', 'cro-0224', '--verb=get,list', '--resource=pods', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0224" in result.stdout
