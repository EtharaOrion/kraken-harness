def test_create_clusterrole_0213_ok(cli):
    result = cli("create", 'clusterrole', 'ccl-0213', '--verb=get,list', '--resource=pods')
    assert result.returncode == 0, result.stderr
    assert "ccl-0213" in result.stdout
