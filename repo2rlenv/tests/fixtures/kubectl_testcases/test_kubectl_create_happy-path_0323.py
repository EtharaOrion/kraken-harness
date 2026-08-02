def test_create_resourcequota_0323_ok(cli):
    result = cli("create", 'resourcequota', 'cre-0323', '--hard=pods=10', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cre-0323" in result.stdout
