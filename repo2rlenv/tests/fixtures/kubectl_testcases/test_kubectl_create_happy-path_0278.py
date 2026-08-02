def test_create_rolebinding_0278_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0278', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0278" in result.stdout
