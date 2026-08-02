def test_create_job_0152_ok(cli):
    result = cli("create", 'job', 'cjo-0152', '--image=busybox', '--', 'echo', 'hi', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cjo-0152" in result.stdout
