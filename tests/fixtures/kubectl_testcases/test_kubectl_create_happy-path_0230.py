def test_create_role_0230_ok(cli):
    result = cli("create", 'role', 'cro-0230', '--verb=get,list', '--resource=pods', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0230" in result.stdout
