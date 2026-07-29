def test_create_rolebinding_0288_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0288', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0288" in result.stdout
