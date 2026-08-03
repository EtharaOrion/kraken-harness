def test_describe_no_resource_type_errors(cli):
    result = cli("describe")
    assert result.returncode == 1
    stderr = result.stderr.lower()
    assert "required" in stderr or "resource" in stderr or "usage" in stderr or "you must" in stderr
