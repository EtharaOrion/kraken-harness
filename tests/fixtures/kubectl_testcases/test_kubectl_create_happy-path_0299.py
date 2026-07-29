def test_create_priorityclass_0299_ok(cli):
    result = cli("create", 'priorityclass', 'cpr-0299', '--value=1000')
    assert result.returncode == 0, result.stderr
    assert "cpr-0299" in result.stdout
