def test_create_job_0162_ok(cli):
    result = cli("create", 'job', 'cjo-0162', '--image=busybox', '--', 'echo', 'hi', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cjo-0162" in result.stdout
