def test_create_resourcequota_0324_ok(cli):
    result = cli("create", 'resourcequota', 'cre-0324', '--hard=pods=10', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cre-0324" in result.stdout
