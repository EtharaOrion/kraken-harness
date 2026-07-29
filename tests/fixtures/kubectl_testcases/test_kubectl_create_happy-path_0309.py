def test_create_priorityclass_0309_ok(cli):
    result = cli("create", 'priorityclass', 'cpr-0309', '--value=1000')
    assert result.returncode == 0, result.stderr
    assert "cpr-0309" in result.stdout
