def test_create_clusterrolebinding_0261_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0261', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0261" in result.stdout
