def test_create_rolebinding_0291_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0291', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0291" in result.stdout
