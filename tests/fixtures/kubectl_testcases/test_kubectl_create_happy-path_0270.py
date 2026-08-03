def test_create_rolebinding_0270_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0270', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0270" in result.stdout
