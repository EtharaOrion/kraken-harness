def test_create_role_0238_ok(cli):
    result = cli("create", 'role', 'cro-0238', '--verb=get,list', '--resource=pods', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0238" in result.stdout
