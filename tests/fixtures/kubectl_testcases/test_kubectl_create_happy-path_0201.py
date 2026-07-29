def test_create_clusterrole_0201_ok(cli):
    result = cli("create", 'clusterrole', 'ccl-0201', '--verb=get,list', '--resource=pods')
    assert result.returncode == 0, result.stderr
    assert "ccl-0201" in result.stdout
