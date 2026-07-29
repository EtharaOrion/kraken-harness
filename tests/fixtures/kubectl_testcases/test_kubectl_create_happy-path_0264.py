def test_create_clusterrolebinding_0264_ok(cli):
    result = cli("create", 'clusterrolebinding', 'ccl-0264', '--clusterrole=view', '--serviceaccount=default:default')
    assert result.returncode == 0, result.stderr
    assert "ccl-0264" in result.stdout
