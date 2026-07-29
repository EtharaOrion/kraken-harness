def test_workflow_create_ns_apply_pod_delete_ns_cleans_up(cli, k8s_client, kubectl_bin, tmp_path):
    r_create_ns = cli("create", "namespace", "wf06-ns")
    assert r_create_ns.returncode == 0, r_create_ns.stderr
    manifest = tmp_path / "pod.yaml"
    manifest.write_text(
        "apiVersion: v1\nkind: Pod\nmetadata:\n  name: wf06-pod\n  namespace: wf06-ns\n"
        "spec:\n  containers: [{name: c, image: nginx}]\n"
    )
    r_apply = cli("apply", "-f", str(manifest))
    assert r_apply.returncode == 0, r_apply.stderr
    pods_in_ns = k8s_client.list_namespaced_pod(namespace="wf06-ns").items
    assert any(p.metadata.name == "wf06-pod" for p in pods_in_ns)
    r_del_ns = cli("delete", "namespace", "wf06-ns")
    assert r_del_ns.returncode == 0, r_del_ns.stderr
    ns_names = {n.metadata.name for n in k8s_client.list_namespace().items}
    assert "wf06-ns" not in ns_names
