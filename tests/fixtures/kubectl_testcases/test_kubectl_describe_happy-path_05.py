def test_describe_pods_by_label_shows_all(cli, k8s_client, kubectl_bin, tmp_path):
    label_val = "hp05"
    for i in range(2):
        pod = tmp_path / f"pod-{i}.yaml"
        pod.write_text(
            f"apiVersion: v1\nkind: Pod\nmetadata:\n  name: hp05-pod-{i}\n  namespace: default\n"
            f"  labels: {{group: {label_val}}}\n"
            "spec:\n  containers: [{name: c, image: nginx}]\n"
        )
        seed = kubectl_bin(["apply", "-f", str(pod)])
        assert seed.returncode == 0, seed.stderr
    result = cli("describe", "pods", "-l", f"group={label_val}", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "hp05-pod-0" in result.stdout
    assert "hp05-pod-1" in result.stdout
    pods = k8s_client.list_namespaced_pod(namespace="default", label_selector=f"group={label_val}").items
    assert len(pods) == 2
