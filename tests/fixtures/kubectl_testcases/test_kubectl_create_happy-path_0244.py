def test_create_role_0244_ok(cli):
    result = cli("create", 'role', 'cro-0244', '--verb=get,list', '--resource=pods', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0244" in result.stdout
