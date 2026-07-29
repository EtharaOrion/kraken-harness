def test_create_role_0234_ok(cli):
    result = cli("create", 'role', 'cro-0234', '--verb=get,list', '--resource=pods', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0234" in result.stdout
