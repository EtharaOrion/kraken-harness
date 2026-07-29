def test_create_job_0164_ok(cli):
    result = cli("create", 'job', 'cjo-0164', '--image=busybox', '--', 'echo', 'hi', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cjo-0164" in result.stdout
