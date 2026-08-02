def test_create_role_0229_ok(cli):
    result = cli("create", 'role', 'cro-0229', '--verb=get,list', '--resource=pods', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0229" in result.stdout
