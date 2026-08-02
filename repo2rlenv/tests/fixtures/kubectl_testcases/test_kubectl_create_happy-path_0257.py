def test_create_clusterrolebinding_0257_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0257', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0257" in result.stdout
