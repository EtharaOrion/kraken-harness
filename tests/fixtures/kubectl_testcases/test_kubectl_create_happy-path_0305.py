def test_create_priorityclass_0305_ok(cli):
    result = cli("create", 'priorityclass', 'cpr-0305', '--value=1000')
    assert result.returncode == 0, result.stderr
    assert "cpr-0305" in result.stdout
