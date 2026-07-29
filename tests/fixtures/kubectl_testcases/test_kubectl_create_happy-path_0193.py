def test_create_cronjob_0193_ok(cli):
    result = cli("create", 'cronjob', 'ccr-0193', '--image=busybox', '--schedule=*/5 * * * *', '--', 'echo', 'hi', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "ccr-0193" in result.stdout
