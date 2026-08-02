def test_create_rolebinding_0274_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0274', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0274" in result.stdout
