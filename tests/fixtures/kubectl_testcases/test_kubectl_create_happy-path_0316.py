def test_create_priorityclass_0316_ok(cli):
    result = cli("create", 'priorityclass', 'cpr-0316', '--value=1000')
    assert result.returncode == 0, result.stderr
    assert "cpr-0316" in result.stdout
