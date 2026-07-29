def test_create_resourcequota_0336_ok(cli):
    result = cli("create", 'resourcequota', 'cre-0336', '--hard=pods=10', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cre-0336" in result.stdout
