def test_patch_pod_in_nonexistent_namespace_returns_notfound(cli, k8s_client):
    result = cli("patch", "pod", "some-pod", "-n", "nonexistent-pt-ne03-ns", "-p", '{"metadata":{"labels":{"a":"b"}}}')
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
    namespaces = k8s_client.list_namespace().items
    assert not any(n.metadata.name == "nonexistent-pt-ne03-ns" for n in namespaces)
