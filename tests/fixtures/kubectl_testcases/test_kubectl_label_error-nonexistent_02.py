from kubernetes import client


def test_label_deployment_nonexistent_returns_notfound(cli, k8s_client):
    result = cli("label", "deployment", "nonexistent-lbl-ne02", "-n", "default", "env=x")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
    apps = client.AppsV1Api(k8s_client.api_client)
    deps = apps.list_namespaced_deployment(namespace="default").items
    assert not any(d.metadata.name == "nonexistent-lbl-ne02" for d in deps)
