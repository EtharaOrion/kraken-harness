def test_create_poddisruptionbudget_0349_ok(cli):
    result = cli("create", 'poddisruptionbudget', 'cpo-0349', '--selector=app=demo', '--min-available=1', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cpo-0349" in result.stdout
