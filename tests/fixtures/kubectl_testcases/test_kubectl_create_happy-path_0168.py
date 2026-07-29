def test_create_job_0168_ok(cli):
    result = cli("create", 'job', 'cjo-0168', '--image=busybox', '--', 'echo', 'hi', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cjo-0168" in result.stdout
