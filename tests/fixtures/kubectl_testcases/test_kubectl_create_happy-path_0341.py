def test_create_resourcequota_0341_ok(cli):
    result = cli("create", 'resourcequota', 'cre-0341', '--hard=pods=10', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cre-0341" in result.stdout
