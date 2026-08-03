def test_create_clusterrolebinding_0252_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0252', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0252" in result.stdout
