def test_create_resourcequota_0321_ok(cli):
    result = cli("create", 'resourcequota', 'cre-0321', '--hard=pods=10', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cre-0321" in result.stdout
