def test_create_cronjob_0181_ok(cli):
    result = cli("create", 'cronjob', 'ccr-0181', '--image=busybox', '--schedule=*/5 * * * *', '--', 'echo', 'hi', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "ccr-0181" in result.stdout
