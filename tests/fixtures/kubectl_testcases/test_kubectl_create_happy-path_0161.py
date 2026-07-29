def test_create_job_0161_ok(cli):
    result = cli("create", 'job', 'cjo-0161', '--image=busybox', '--', 'echo', 'hi', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cjo-0161" in result.stdout
