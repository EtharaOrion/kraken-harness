def test_create_role_0228_ok(cli):
    result = cli("create", 'role', 'cro-0228', '--verb=get,list', '--resource=pods', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0228" in result.stdout
