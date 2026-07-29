def test_create_role_0245_ok(cli):
    result = cli("create", 'role', 'cro-0245', '--verb=get,list', '--resource=pods', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0245" in result.stdout
