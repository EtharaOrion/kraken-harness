def test_create_clusterrolebinding_0256_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0256', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0256" in result.stdout
