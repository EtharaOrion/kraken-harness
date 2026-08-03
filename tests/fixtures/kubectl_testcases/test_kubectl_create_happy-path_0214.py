def test_create_clusterrole_0214_ok(cli):
    result = cli("create", 'clusterrole', 'ccl-0214', '--verb=get,list', '--resource=pods')
    assert result.returncode == 0, result.stderr
    assert "ccl-0214" in result.stdout
