def test_create_clusterrole_0221_ok(cli):
    result = cli("create", 'clusterrole', 'ccl-0221', '--verb=get,list', '--resource=pods')
    assert result.returncode == 0, result.stderr
    assert "ccl-0221" in result.stdout
