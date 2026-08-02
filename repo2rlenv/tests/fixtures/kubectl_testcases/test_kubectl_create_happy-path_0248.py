def test_create_clusterrolebinding_0248_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0248', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0248" in result.stdout
