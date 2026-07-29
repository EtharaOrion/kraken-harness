def test_create_clusterrolebinding_0260_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0260', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0260" in result.stdout
