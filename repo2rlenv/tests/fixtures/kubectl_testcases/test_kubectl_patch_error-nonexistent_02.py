from kubernetes import client


def test_patch_deployment_nonexistent_returns_notfound(cli, k8s_client):
    apps = client.AppsV1Api(k8s_client.api_client)
    result = cli("patch", "deployment", "nonexistent-pt-ne02", "-n", "default", "-p", '{"spec":{"replicas":2}}')
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
    deps = apps.list_namespaced_deployment(namespace="default").items
    assert not any(d.metadata.name == "nonexistent-pt-ne02" for d in deps)
