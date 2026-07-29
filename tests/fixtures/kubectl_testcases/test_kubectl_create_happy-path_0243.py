def test_create_role_0243_ok(cli):
    result = cli("create", 'role', 'cro-0243', '--verb=get,list', '--resource=pods', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0243" in result.stdout
