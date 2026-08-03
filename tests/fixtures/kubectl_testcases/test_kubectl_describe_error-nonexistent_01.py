def test_describe_pod_nonexistent_returns_notfound(cli, k8s_client):
    result = cli("describe", "pod", "nonexistent-desc-ne01", "-n", "default")
    assert result.returncode == 1
    assert "not found" in result.stderr.lower() or "notfound" in result.stderr.lower()
    pods = k8s_client.list_namespaced_pod(namespace="default").items
    assert not any(p.metadata.name == "nonexistent-desc-ne01" for p in pods)
