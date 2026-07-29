def test_delete_nonexistent_pod_returns_notfound(cli, k8s_client):
    result = cli("delete", "pod", "nonexistent-del-ne01", "-n", "default")
    assert result.returncode == 1
    stderr = result.stderr.lower()
    assert "not found" in stderr or "notfound" in stderr
    pods = k8s_client.list_namespaced_pod(namespace="default").items
    assert not any(p.metadata.name == "nonexistent-del-ne01" for p in pods)
