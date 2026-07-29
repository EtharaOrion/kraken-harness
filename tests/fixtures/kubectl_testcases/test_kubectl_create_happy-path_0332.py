def test_create_resourcequota_0332_ok(cli):
    result = cli("create", 'resourcequota', 'cre-0332', '--hard=pods=10', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cre-0332" in result.stdout
