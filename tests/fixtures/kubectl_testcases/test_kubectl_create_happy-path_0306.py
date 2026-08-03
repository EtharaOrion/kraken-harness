def test_create_priorityclass_0306_ok(cli):
    result = cli("create", 'priorityclass', 'cpr-0306', '--value=1000')
    assert result.returncode == 0, result.stderr
    assert "cpr-0306" in result.stdout
