def test_scale_deployment_missing_replicas_flag(cli, k8s_client):
    result = cli("scale", "deployment", "some-dep", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "required" in err or "replicas" in err or "must" in err
