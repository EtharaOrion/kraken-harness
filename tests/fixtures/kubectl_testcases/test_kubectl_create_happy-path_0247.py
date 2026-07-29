def test_create_clusterrolebinding_0247_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0247', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0247" in result.stdout
