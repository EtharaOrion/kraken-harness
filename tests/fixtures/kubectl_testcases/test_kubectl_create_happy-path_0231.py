def test_create_role_0231_ok(cli):
    result = cli("create", 'role', 'cro-0231', '--verb=get,list', '--resource=pods', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0231" in result.stdout
