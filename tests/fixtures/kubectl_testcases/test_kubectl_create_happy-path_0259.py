def test_create_clusterrolebinding_0259_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0259', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0259" in result.stdout
