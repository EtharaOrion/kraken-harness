def test_create_clusterrole_0198_ok(cli):
    result = cli("create", 'clusterrole', 'ccl-0198', '--verb=get,list', '--resource=pods')
    assert result.returncode == 0, result.stderr
    assert "ccl-0198" in result.stdout
