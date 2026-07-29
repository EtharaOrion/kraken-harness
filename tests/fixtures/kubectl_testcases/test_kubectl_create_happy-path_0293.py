def test_create_rolebinding_0293_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0293', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0293" in result.stdout
