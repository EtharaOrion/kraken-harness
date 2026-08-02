def test_create_clusterrole_0219_ok(cli):
    result = cli("create", 'clusterrole', 'ccl-0219', '--verb=get,list', '--resource=pods')
    assert result.returncode == 0, result.stderr
    assert "ccl-0219" in result.stdout
