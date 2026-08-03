def test_create_cronjob_0190_ok(cli):
    result = cli("create", 'cronjob', 'ccr-0190', '--image=busybox', '--schedule=*/5 * * * *', '--', 'echo', 'hi', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "ccr-0190" in result.stdout
