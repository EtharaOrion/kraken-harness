def test_create_poddisruptionbudget_0346_ok(cli):
    result = cli("create", 'poddisruptionbudget', 'cpo-0346', '--selector=app=demo', '--min-available=1', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cpo-0346" in result.stdout
