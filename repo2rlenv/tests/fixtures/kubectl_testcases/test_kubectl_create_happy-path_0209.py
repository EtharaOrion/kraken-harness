def test_create_clusterrole_0209_ok(cli):
    result = cli("create", 'clusterrole', 'ccl-0209', '--verb=get,list', '--resource=pods')
    assert result.returncode == 0, result.stderr
    assert "ccl-0209" in result.stdout
