def test_create_job_0158_ok(cli):
    result = cli("create", 'job', 'cjo-0158', '--image=busybox', '--', 'echo', 'hi', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cjo-0158" in result.stdout
