def test_create_rolebinding_0279_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0279', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0279" in result.stdout
