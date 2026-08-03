def test_create_clusterrole_0204_ok(cli):
    result = cli("create", 'clusterrole', 'ccl-0204', '--verb=get,list', '--resource=pods')
    assert result.returncode == 0, result.stderr
    assert "ccl-0204" in result.stdout
