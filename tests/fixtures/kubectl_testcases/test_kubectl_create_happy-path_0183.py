def test_create_cronjob_0183_ok(cli):
    result = cli("create", 'cronjob', 'ccr-0183', '--image=busybox', '--schedule=*/5 * * * *', '--', 'echo', 'hi', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "ccr-0183" in result.stdout
