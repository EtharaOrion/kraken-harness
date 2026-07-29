def test_create_rolebinding_0273_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0273', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0273" in result.stdout
