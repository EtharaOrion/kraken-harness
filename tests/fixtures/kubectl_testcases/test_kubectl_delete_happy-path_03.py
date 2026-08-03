def test_delete_pods_by_label_removes_all(cli, k8s_client, kubectl_bin, tmp_path):
    label_val = "del-hp03"
    pod_a = "pod-del-hp03-a"
    pod_b = "pod-del-hp03-b"
    manifest = tmp_path / "pods.yaml"
    manifest.write_text(
        f"apiVersion: v1\nkind: Pod\nmetadata:\n  name: {pod_a}\n  namespace: default\n"
        f"  labels: {{app: {label_val}}}\n"
        "spec:\n  containers: [{name: c, image: nginx}]\n"
        "---\n"
        f"apiVersion: v1\nkind: Pod\nmetadata:\n  name: {pod_b}\n  namespace: default\n"
        f"  labels: {{app: {label_val}}}\n"
        "spec:\n  containers: [{name: c, image: nginx}]\n"
    )
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("delete", "pods", "-l", f"app={label_val}", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "deleted" in result.stdout.lower()
    pods = k8s_client.list_namespaced_pod(namespace="default").items
    names = {p.metadata.name for p in pods}
    assert pod_a not in names
    assert pod_b not in names
