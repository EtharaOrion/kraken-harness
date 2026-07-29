def test_create_priorityclass_0310_ok(cli):
    result = cli("create", 'priorityclass', 'cpr-0310', '--value=1000')
    assert result.returncode == 0, result.stderr
    assert "cpr-0310" in result.stdout
