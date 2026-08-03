def test_create_job_0169_ok(cli):
    result = cli("create", 'job', 'cjo-0169', '--image=busybox', '--', 'echo', 'hi', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cjo-0169" in result.stdout
