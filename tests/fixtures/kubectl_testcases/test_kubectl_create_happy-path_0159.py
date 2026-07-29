def test_create_job_0159_ok(cli):
    result = cli("create", 'job', 'cjo-0159', '--image=busybox', '--', 'echo', 'hi', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cjo-0159" in result.stdout
