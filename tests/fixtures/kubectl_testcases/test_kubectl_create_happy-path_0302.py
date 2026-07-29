def test_create_priorityclass_0302_ok(cli):
    result = cli("create", 'priorityclass', 'cpr-0302', '--value=1000')
    assert result.returncode == 0, result.stderr
    assert "cpr-0302" in result.stdout
