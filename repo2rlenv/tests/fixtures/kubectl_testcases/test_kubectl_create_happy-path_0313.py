def test_create_priorityclass_0313_ok(cli):
    result = cli("create", 'priorityclass', 'cpr-0313', '--value=1000')
    assert result.returncode == 0, result.stderr
    assert "cpr-0313" in result.stdout
