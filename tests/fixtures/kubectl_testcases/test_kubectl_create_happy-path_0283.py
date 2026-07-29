def test_create_rolebinding_0283_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0283', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0283" in result.stdout
