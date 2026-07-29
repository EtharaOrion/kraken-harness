def test_create_clusterrolebinding_0263_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0263', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0263" in result.stdout
