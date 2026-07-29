def test_create_job_0165_ok(cli):
    result = cli("create", 'job', 'cjo-0165', '--image=busybox', '--', 'echo', 'hi', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "cjo-0165" in result.stdout
