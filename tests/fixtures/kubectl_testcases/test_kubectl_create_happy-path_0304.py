def test_create_priorityclass_0304_ok(cli):
    result = cli("create", 'priorityclass', 'cpr-0304', '--value=1000')
    assert result.returncode == 0, result.stderr
    assert "cpr-0304" in result.stdout
