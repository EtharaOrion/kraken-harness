def test_create_role_0226_ok(cli):
    result = cli("create", 'role', 'cro-0226', '--verb=get,list', '--resource=pods', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0226" in result.stdout
