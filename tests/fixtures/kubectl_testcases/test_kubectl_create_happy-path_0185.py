def test_create_cronjob_0185_ok(cli):
    result = cli("create", 'cronjob', 'ccr-0185', '--image=busybox', '--schedule=*/5 * * * *', '--', 'echo', 'hi', "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "ccr-0185" in result.stdout
