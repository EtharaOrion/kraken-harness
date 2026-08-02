def test_create_job_0166_ok(cli):
    result = cli("create", 'job', 'cjo-0166', '--image=busybox', '--', 'echo', 'hi', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cjo-0166" in result.stdout
