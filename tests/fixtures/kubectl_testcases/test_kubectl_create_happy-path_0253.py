def test_create_clusterrolebinding_0253_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0253', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0253" in result.stdout
