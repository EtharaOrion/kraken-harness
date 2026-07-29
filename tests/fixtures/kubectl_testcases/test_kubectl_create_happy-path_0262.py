def test_create_clusterrolebinding_0262_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0262', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0262" in result.stdout
