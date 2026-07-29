def test_create_resourcequota_0326_ok(cli):
    result = cli("create", 'resourcequota', 'cre-0326', '--hard=pods=10', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cre-0326" in result.stdout
