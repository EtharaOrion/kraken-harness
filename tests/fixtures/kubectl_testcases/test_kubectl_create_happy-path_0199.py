def test_create_clusterrole_0199_ok(cli):
    result = cli("create", 'clusterrole', 'ccl-0199', '--verb=get,list', '--resource=pods')
    assert result.returncode == 0, result.stderr
    assert "ccl-0199" in result.stdout
