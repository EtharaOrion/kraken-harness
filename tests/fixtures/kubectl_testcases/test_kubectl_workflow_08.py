def test_workflow_apply_pod_describe_delete_get_returns_notfound(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "pod.yaml"
    manifest.write_text(
        "apiVersion: v1\nkind: Pod\nmetadata:\n  name: wf08-pod\n  namespace: default\n"
        "spec:\n  containers: [{name: c, image: nginx}]\n"
    )
    r_apply = cli("apply", "-f", str(manifest))
    assert r_apply.returncode == 0, r_apply.stderr
    r_desc = cli("describe", "pod", "wf08-pod", "-n", "default")
    assert r_desc.returncode == 0, r_desc.stderr
    assert "wf08-pod" in r_desc.stdout
    r_del = cli("delete", "pod", "wf08-pod", "-n", "default")
    assert r_del.returncode == 0, r_del.stderr
    r_get_gone = cli("get", "pod", "wf08-pod", "-n", "default")
    assert r_get_gone.returncode == 1
    assert "not found" in r_get_gone.stderr.lower() or "notfound" in r_get_gone.stderr.lower()
    pods = k8s_client.list_namespaced_pod(namespace="default").items
    assert not any(p.metadata.name == "wf08-pod" for p in pods)
