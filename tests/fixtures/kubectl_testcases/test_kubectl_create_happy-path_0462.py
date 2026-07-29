def test_create_ingress_0462_ok(cli):
    result = cli("create", 'ingress', 'cin-0462', '--rule=example.local/=demo:80', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cin-0462" in result.stdout
