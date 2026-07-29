def test_create_job_0150_ok(cli):
    result = cli("create", 'job', 'cjo-0150', '--image=busybox', '--', 'echo', 'hi', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cjo-0150" in result.stdout
