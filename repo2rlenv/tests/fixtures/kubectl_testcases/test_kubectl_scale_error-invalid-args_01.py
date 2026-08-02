def test_scale_deployment_unknown_flag(cli, k8s_client):
    result = cli("scale", "deployment", "some-dep", "--invalid-flag", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err
