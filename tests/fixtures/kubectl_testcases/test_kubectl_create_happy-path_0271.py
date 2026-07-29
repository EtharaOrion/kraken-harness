def test_create_rolebinding_0271_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0271', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0271" in result.stdout
