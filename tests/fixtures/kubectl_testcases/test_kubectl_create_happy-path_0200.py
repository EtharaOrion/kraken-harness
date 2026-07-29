def test_create_clusterrole_0200_ok(cli):
    result = cli("create", 'clusterrole', 'ccl-0200', '--verb=get,list', '--resource=pods')
    assert result.returncode == 0, result.stderr
    assert "ccl-0200" in result.stdout
