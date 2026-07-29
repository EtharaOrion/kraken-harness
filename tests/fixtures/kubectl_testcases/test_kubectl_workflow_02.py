def test_workflow_apply_pod_then_label_then_get_then_delete(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "pod.yaml"
    manifest.write_text(
        "apiVersion: v1\nkind: Pod\nmetadata:\n  name: wf02-pod\n  namespace: default\n"
        "spec:\n  containers: [{name: c, image: nginx}]\n"
    )
    r_apply = cli("apply", "-f", str(manifest))
    assert r_apply.returncode == 0, r_apply.stderr
    r_label = cli("label", "pod", "wf02-pod", "tier=frontend", "-n", "default")
    assert r_label.returncode == 0, r_label.stderr
    r_get = cli("get", "pods", "-l", "tier=frontend", "-n", "default")
    assert r_get.returncode == 0, r_get.stderr
    assert "wf02-pod" in r_get.stdout
    pod = next(p for p in k8s_client.list_namespaced_pod(namespace="default").items if p.metadata.name == "wf02-pod")
    assert pod.metadata.labels.get("tier") == "frontend"
    r_del = cli("delete", "pod", "wf02-pod", "-n", "default")
    assert r_del.returncode == 0, r_del.stderr
    pods_after = k8s_client.list_namespaced_pod(namespace="default").items
    assert not any(p.metadata.name == "wf02-pod" for p in pods_after)
