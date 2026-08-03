def test_create_resourcequota_0333_ok(cli):
    result = cli("create", 'resourcequota', 'cre-0333', '--hard=pods=10', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cre-0333" in result.stdout
