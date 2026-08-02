def test_create_resourcequota_0320_ok(cli):
    result = cli("create", 'resourcequota', 'cre-0320', '--hard=pods=10', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cre-0320" in result.stdout
