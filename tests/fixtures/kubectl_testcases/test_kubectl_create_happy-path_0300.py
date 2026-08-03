def test_create_priorityclass_0300_ok(cli):
    result = cli("create", 'priorityclass', 'cpr-0300', '--value=1000')
    assert result.returncode == 0, result.stderr
    assert "cpr-0300" in result.stdout
