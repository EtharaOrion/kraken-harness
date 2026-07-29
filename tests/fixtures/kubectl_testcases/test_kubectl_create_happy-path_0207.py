def test_create_clusterrole_0207_ok(cli):
    result = cli("create", 'clusterrole', 'ccl-0207', '--verb=get,list', '--resource=pods')
    assert result.returncode == 0, result.stderr
    assert "ccl-0207" in result.stdout
