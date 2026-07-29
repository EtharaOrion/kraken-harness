def test_create_job_0171_ok(cli):
    result = cli("create", 'job', 'cjo-0171', '--image=busybox', '--', 'echo', 'hi', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cjo-0171" in result.stdout
