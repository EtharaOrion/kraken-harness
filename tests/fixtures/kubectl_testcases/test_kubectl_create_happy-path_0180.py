def test_create_cronjob_0180_ok(cli):
    result = cli("create", 'cronjob', 'ccr-0180', '--image=busybox', '--schedule=*/5 * * * *', '--', 'echo', 'hi', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "ccr-0180" in result.stdout
