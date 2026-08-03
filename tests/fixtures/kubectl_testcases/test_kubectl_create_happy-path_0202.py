def test_create_clusterrole_0202_ok(cli):
    result = cli("create", 'clusterrole', 'ccl-0202', '--verb=get,list', '--resource=pods')
    assert result.returncode == 0, result.stderr
    assert "ccl-0202" in result.stdout
