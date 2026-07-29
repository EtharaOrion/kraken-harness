def test_create_job_0170_ok(cli):
    result = cli("create", 'job', 'cjo-0170', '--image=busybox', '--', 'echo', 'hi', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cjo-0170" in result.stdout
