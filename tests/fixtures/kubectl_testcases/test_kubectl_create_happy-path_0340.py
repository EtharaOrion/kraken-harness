def test_create_resourcequota_0340_ok(cli):
    result = cli("create", 'resourcequota', 'cre-0340', '--hard=pods=10', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cre-0340" in result.stdout
