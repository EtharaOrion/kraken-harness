def test_create_clusterrolebinding_0269_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0269', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0269" in result.stdout
