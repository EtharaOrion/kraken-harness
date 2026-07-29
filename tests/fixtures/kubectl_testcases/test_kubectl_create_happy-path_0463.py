def test_create_ingress_0463_ok(cli):
    result = cli("create", 'ingress', 'cin-0463', '--rule=example.local/=demo:80', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cin-0463" in result.stdout
