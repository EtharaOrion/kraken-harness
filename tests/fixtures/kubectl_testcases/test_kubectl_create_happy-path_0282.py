def test_create_rolebinding_0282_ok(cli):
    result = cli("create", 'rolebinding', 'cro-0282', '--role=view', '--serviceaccount=default:default', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cro-0282" in result.stdout
