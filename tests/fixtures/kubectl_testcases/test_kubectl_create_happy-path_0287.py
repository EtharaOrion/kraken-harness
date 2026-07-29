def test_create_rolebinding_0287_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0287', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0287" in result.stdout
