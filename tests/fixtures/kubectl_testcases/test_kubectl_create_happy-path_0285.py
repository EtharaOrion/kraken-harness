def test_create_rolebinding_0285_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0285', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0285" in result.stdout
