def test_create_priorityclass_0295_ok(cli):
    result = cli("create", 'priorityclass', 'cpr-0295', '--value=1000')
    assert result.returncode == 0, result.stderr
    assert "cpr-0295" in result.stdout
