def test_create_rolebinding_0272_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0272', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0272" in result.stdout
