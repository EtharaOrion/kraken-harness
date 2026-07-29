def test_patch_pod_nonexistent_returns_notfound(cli, k8s_client):
    result = cli("patch", "pod", "nonexistent-pt-ne01", "-n", "default", "-p", '{"metadata":{"labels":{"a":"b"}}}')
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
    pods = k8s_client.list_namespaced_pod(namespace="default").items
    assert not any(p.metadata.name == "nonexistent-pt-ne01" for p in pods)
