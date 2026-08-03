def test_create_clusterrole_0218_ok(cli):
    result = cli("create", 'clusterrole', 'ccl-0218', '--verb=get,list', '--resource=pods')
    assert result.returncode == 0, result.stderr
    assert "ccl-0218" in result.stdout
