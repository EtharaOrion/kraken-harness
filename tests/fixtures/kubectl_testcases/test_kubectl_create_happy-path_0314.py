def test_create_priorityclass_0314_ok(cli):
    result = cli("create", 'priorityclass', 'cpr-0314', '--value=1000')
    assert result.returncode == 0, result.stderr
    assert "cpr-0314" in result.stdout
