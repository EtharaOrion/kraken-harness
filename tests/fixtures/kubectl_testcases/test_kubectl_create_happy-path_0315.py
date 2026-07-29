def test_create_priorityclass_0315_ok(cli):
    result = cli("create", 'priorityclass', 'cpr-0315', '--value=1000')
    assert result.returncode == 0, result.stderr
    assert "cpr-0315" in result.stdout
