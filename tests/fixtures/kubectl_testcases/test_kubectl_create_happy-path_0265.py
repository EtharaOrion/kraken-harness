def test_create_clusterrolebinding_0265_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0265', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0265" in result.stdout
