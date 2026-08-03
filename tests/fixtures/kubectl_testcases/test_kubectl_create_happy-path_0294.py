def test_create_priorityclass_0294_ok(cli):
    result = cli("create", 'priorityclass', 'cpr-0294', '--value=1000')
    assert result.returncode == 0, result.stderr
    assert "cpr-0294" in result.stdout
