def test_create_resourcequota_0322_ok(cli):
    result = cli("create", 'resourcequota', 'cre-0322', '--hard=pods=10', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cre-0322" in result.stdout
