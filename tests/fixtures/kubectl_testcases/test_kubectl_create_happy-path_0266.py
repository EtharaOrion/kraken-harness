def test_create_clusterrolebinding_0266_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0266', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0266" in result.stdout
