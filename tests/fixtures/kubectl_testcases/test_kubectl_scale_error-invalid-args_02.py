def test_scale_deployment_non_integer_replicas(cli, k8s_client):
    result = cli("scale", "deployment", "some-dep", "--replicas=abc", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "invalid" in err or "parse" in err or "integer" in err
