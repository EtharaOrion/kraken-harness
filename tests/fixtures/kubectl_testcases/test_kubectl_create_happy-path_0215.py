def test_create_clusterrole_0215_ok(cli):
    result = cli("create", 'clusterrole', 'ccl-0215', '--verb=get,list', '--resource=pods')
    assert result.returncode == 0, result.stderr
    assert "ccl-0215" in result.stdout
