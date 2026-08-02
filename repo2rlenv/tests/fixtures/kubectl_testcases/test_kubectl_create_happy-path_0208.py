def test_create_clusterrole_0208_ok(cli):
    result = cli("create", 'clusterrole', 'ccl-0208', '--verb=get,list', '--resource=pods')
    assert result.returncode == 0, result.stderr
    assert "ccl-0208" in result.stdout
