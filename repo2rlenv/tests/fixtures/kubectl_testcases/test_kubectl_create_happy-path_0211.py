def test_create_clusterrole_0211_ok(cli):
    result = cli("create", 'clusterrole', 'ccl-0211', '--verb=get,list', '--resource=pods')
    assert result.returncode == 0, result.stderr
    assert "ccl-0211" in result.stdout
