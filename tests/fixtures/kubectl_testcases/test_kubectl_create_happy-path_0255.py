def test_create_clusterrolebinding_0255_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0255', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0255" in result.stdout
