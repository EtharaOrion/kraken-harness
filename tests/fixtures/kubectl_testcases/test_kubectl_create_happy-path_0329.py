def test_create_resourcequota_0329_ok(cli):
    result = cli("create", 'resourcequota', 'cre-0329', '--hard=pods=10', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cre-0329" in result.stdout
