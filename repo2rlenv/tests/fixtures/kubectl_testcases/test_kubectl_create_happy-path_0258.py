def test_create_clusterrolebinding_0258_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0258', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0258" in result.stdout
