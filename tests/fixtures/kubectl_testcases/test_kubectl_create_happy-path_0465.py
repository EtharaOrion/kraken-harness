def test_create_ingress_0465_ok(cli):
    result = cli("create", 'ingress', 'cin-0465', '--rule=example.local/=demo:80', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cin-0465" in result.stdout
