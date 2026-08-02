def test_create_priorityclass_0298_ok(cli):
    result = cli("create", 'priorityclass', 'cpr-0298', '--value=1000')
    assert result.returncode == 0, result.stderr
    assert "cpr-0298" in result.stdout
