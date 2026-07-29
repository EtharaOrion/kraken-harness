def test_workflow_apply_delete_by_manifest_file(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "pod.yaml"
    manifest.write_text(
        "apiVersion: v1\nkind: Pod\nmetadata:\n  name: wf12-pod\n  namespace: default\n"
        "spec:\n  containers: [{name: c, image: nginx}]\n"
    )
    r_apply = cli("apply", "-f", str(manifest))
    assert r_apply.returncode == 0, r_apply.stderr
    pods_before = k8s_client.list_namespaced_pod(namespace="default").items
    assert any(p.metadata.name == "wf12-pod" for p in pods_before)
    r_del = cli("delete", "-f", str(manifest))
    assert r_del.returncode == 0, r_del.stderr
    pods_after = k8s_client.list_namespaced_pod(namespace="default").items
    assert not any(p.metadata.name == "wf12-pod" for p in pods_after)
