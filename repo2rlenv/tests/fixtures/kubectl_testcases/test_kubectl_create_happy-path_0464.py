def test_create_ingress_0464_ok(cli):
    result = cli("create", 'ingress', 'cin-0464', '--rule=example.local/=demo:80', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cin-0464" in result.stdout
