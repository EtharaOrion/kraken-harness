def test_create_resourcequota_0335_ok(cli):
    result = cli("create", 'resourcequota', 'cre-0335', '--hard=pods=10', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cre-0335" in result.stdout
