def test_create_rolebinding_0276_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0276', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0276" in result.stdout
