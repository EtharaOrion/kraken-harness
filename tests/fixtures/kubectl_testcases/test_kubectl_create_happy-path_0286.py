def test_create_rolebinding_0286_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0286', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0286" in result.stdout
