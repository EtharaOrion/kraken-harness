def test_create_rolebinding_0292_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0292', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0292" in result.stdout
