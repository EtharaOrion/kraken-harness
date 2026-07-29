def test_create_resourcequota_0318_ok(cli):
    result = cli("create", 'resourcequota', 'cre-0318', '--hard=pods=10', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cre-0318" in result.stdout
