def test_create_clusterrolebinding_0249_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0249', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0249" in result.stdout
