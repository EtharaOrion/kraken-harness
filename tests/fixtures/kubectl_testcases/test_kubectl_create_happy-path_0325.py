def test_create_resourcequota_0325_ok(cli):
    result = cli("create", 'resourcequota', 'cre-0325', '--hard=pods=10', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cre-0325" in result.stdout
