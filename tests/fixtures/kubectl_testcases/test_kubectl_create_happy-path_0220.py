def test_create_clusterrole_0220_ok(cli):
    result = cli("create", 'clusterrole', 'ccl-0220', '--verb=get,list', '--resource=pods')
    assert result.returncode == 0, result.stderr
    assert "ccl-0220" in result.stdout
