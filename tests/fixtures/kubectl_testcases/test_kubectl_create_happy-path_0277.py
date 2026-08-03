def test_create_rolebinding_0277_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0277', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0277" in result.stdout
