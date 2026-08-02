def test_create_clusterrole_0210_ok(cli):
    result = cli("create", 'clusterrole', 'ccl-0210', '--verb=get,list', '--resource=pods')
    assert result.returncode == 0, result.stderr
    assert "ccl-0210" in result.stdout
