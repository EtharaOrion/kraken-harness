def test_create_priorityclass_0317_ok(cli):
    result = cli("create", 'priorityclass', 'cpr-0317', '--value=1000')
    assert result.returncode == 0, result.stderr
    assert "cpr-0317" in result.stdout
