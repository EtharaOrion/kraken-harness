def test_label_pods_by_selector_adds_label(cli, k8s_client, kubectl_bin, tmp_path):
    suffix = tmp_path.name.replace('_', '-').lower()[:20]
    pod_a = f"pod-lbl-hp05a-{suffix}"
    pod_b = f"pod-lbl-hp05b-{suffix}"
    manifest = tmp_path / "pods.yaml"
    manifest.write_text(
        f"apiVersion: v1\nkind: Pod\nmetadata:\n  name: {pod_a}\n  namespace: default\n"
        "  labels: {group: g5}\n"
        "spec:\n  containers: [{name: c, image: nginx}]\n"
        "---\n"
        f"apiVersion: v1\nkind: Pod\nmetadata:\n  name: {pod_b}\n  namespace: default\n"
        "  labels: {group: g5}\n"
        "spec:\n  containers: [{name: c, image: nginx}]\n"
    )
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "-l", "group=g5", "pods", "env=test", "-n", "default")
    assert result.returncode == 0, result.stderr
    pa = k8s_client.read_namespaced_pod(name=pod_a, namespace="default")
    pb = k8s_client.read_namespaced_pod(name=pod_b, namespace="default")
    assert pa.metadata.labels.get("env") == "test"
    assert pb.metadata.labels.get("env") == "test"
