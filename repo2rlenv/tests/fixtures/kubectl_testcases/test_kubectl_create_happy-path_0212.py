def test_create_clusterrole_0212_ok(cli):
    result = cli("create", 'clusterrole', 'ccl-0212', '--verb=get,list', '--resource=pods')
    assert result.returncode == 0, result.stderr
    assert "ccl-0212" in result.stdout
