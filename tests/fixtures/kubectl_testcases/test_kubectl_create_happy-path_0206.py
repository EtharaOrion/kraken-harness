def test_create_clusterrole_0206_ok(cli):
    result = cli("create", 'clusterrole', 'ccl-0206', '--verb=get,list', '--resource=pods')
    assert result.returncode == 0, result.stderr
    assert "ccl-0206" in result.stdout
