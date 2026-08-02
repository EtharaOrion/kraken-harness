def test_create_clusterrolebinding_0246_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0246', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0246" in result.stdout
