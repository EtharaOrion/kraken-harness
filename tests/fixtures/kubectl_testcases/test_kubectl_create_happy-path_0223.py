def test_create_role_0223_ok(cli):
    result = cli("create", 'role', 'cro-0223', '--verb=get,list', '--resource=pods', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0223" in result.stdout
