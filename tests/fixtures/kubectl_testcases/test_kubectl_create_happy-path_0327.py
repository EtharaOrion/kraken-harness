def test_create_resourcequota_0327_ok(cli):
    result = cli("create", 'resourcequota', 'cre-0327', '--hard=pods=10', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cre-0327" in result.stdout
