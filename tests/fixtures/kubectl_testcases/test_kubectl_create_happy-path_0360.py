def test_create_poddisruptionbudget_0360_ok(cli):
    result = cli("create", 'poddisruptionbudget', 'cpo-0360', '--selector=app=demo', '--min-available=1', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cpo-0360" in result.stdout
