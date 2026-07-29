def test_create_resourcequota_0334_ok(cli):
    result = cli("create", 'resourcequota', 'cre-0334', '--hard=pods=10', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cre-0334" in result.stdout
