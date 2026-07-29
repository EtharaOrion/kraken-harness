def test_create_rolebinding_0281_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0281', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0281" in result.stdout
