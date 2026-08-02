def test_create_clusterrole_0216_ok(cli):
    result = cli("create", 'clusterrole', 'ccl-0216', '--verb=get,list', '--resource=pods')
    assert result.returncode == 0, result.stderr
    assert "ccl-0216" in result.stdout
