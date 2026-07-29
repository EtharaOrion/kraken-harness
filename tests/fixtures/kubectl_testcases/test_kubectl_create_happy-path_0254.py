def test_create_clusterrolebinding_0254_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0254', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0254" in result.stdout
