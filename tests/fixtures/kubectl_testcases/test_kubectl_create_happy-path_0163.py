def test_create_job_0163_ok(cli):
    result = cli("create", 'job', 'cjo-0163', '--image=busybox', '--', 'echo', 'hi', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cjo-0163" in result.stdout
