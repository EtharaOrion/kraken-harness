def test_create_resourcequota_0319_ok(cli):
    result = cli("create", 'resourcequota', 'cre-0319', '--hard=pods=10', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cre-0319" in result.stdout
