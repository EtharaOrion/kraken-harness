def test_create_clusterrole_0217_ok(cli):
    result = cli("create", 'clusterrole', 'ccl-0217', '--verb=get,list', '--resource=pods')
    assert result.returncode == 0, result.stderr
    assert "ccl-0217" in result.stdout
