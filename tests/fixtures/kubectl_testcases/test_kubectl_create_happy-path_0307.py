def test_create_priorityclass_0307_ok(cli):
    result = cli("create", 'priorityclass', 'cpr-0307', '--value=1000')
    assert result.returncode == 0, result.stderr
    assert "cpr-0307" in result.stdout
