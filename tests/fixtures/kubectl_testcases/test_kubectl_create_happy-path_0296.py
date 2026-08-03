def test_create_priorityclass_0296_ok(cli):
    result = cli("create", 'priorityclass', 'cpr-0296', '--value=1000')
    assert result.returncode == 0, result.stderr
    assert "cpr-0296" in result.stdout
