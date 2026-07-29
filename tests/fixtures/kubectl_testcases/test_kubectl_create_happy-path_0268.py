def test_create_clusterrolebinding_0268_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0268', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0268" in result.stdout
