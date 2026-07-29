def test_create_resourcequota_0338_ok(cli):
    result = cli("create", 'resourcequota', 'cre-0338', '--hard=pods=10', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cre-0338" in result.stdout
