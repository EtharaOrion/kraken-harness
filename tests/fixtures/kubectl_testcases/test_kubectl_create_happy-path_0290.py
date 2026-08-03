def test_create_rolebinding_0290_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0290', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0290" in result.stdout
