def test_create_role_0239_ok(cli):
    result = cli("create", 'role', 'cro-0239', '--verb=get,list', '--resource=pods', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0239" in result.stdout
