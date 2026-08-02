def test_create_resourcequota_0331_ok(cli):
    result = cli("create", 'resourcequota', 'cre-0331', '--hard=pods=10', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cre-0331" in result.stdout
