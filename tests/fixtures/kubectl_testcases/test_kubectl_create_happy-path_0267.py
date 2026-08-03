def test_create_clusterrolebinding_0267_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0267', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0267" in result.stdout
