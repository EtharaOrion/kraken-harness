def test_create_rolebinding_0284_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0284', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0284" in result.stdout
