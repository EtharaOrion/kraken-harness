def test_create_rolebinding_0280_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0280', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0280" in result.stdout
