def test_label_pod_nonexistent_returns_notfound(cli, k8s_client):
    result = cli("label", "pod", "nonexistent-lbl-ne01", "-n", "default", "env=x")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
    pods = k8s_client.list_namespaced_pod(namespace="default").items
    assert not any(p.metadata.name == "nonexistent-lbl-ne01" for p in pods)
