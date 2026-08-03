def test_create_clusterrolebinding_0250_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0250', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0250" in result.stdout
