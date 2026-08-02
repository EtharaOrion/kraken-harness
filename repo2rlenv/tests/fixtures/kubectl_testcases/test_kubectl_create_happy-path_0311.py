def test_create_priorityclass_0311_ok(cli):
    result = cli("create", 'priorityclass', 'cpr-0311', '--value=1000')
    assert result.returncode == 0, result.stderr
    assert "cpr-0311" in result.stdout
