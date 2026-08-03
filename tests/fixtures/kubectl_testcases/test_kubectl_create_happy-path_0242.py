def test_create_role_0242_ok(cli):
    result = cli("create", 'role', 'cro-0242', '--verb=get,list', '--resource=pods', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0242" in result.stdout
