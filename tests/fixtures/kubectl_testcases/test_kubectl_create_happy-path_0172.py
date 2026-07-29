def test_create_job_0172_ok(cli):
    result = cli("create", 'job', 'cjo-0172', '--image=busybox', '--', 'echo', 'hi', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cjo-0172" in result.stdout
