def test_create_rolebinding_0275_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0275', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0275" in result.stdout
