def test_create_clusterrolebinding_0251_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0251', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0251" in result.stdout
