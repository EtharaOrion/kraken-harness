def test_create_resourcequota_0339_ok(cli):
    result = cli("create", 'resourcequota', 'cre-0339', '--hard=pods=10', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cre-0339" in result.stdout
