def test_create_resourcequota_0328_ok(cli):
    result = cli("create", 'resourcequota', 'cre-0328', '--hard=pods=10', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cre-0328" in result.stdout
