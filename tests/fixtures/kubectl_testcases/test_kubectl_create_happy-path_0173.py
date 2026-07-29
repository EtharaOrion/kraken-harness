def test_create_job_0173_ok(cli):
    result = cli("create", 'job', 'cjo-0173', '--image=busybox', '--', 'echo', 'hi', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cjo-0173" in result.stdout
