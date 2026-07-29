def test_create_rolebinding_0289_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0289', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0289" in result.stdout
