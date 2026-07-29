def test_get_pod_yaml_output(cli, k8s_client, kubectl_bin, tmp_path):
    pod_name = "get-hp04-pod"
    manifest = tmp_path / "pod.yaml"
    manifest.write_text(
        f"apiVersion: v1\nkind: Pod\nmetadata:\n  name: {pod_name}\n  namespace: default\n"
        "spec:\n  containers: [{name: c, image: nginx}]\n"
    )
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "pod", pod_name, "-o", "yaml", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "apiVersion: v1" in result.stdout
    assert "kind: Pod" in result.stdout
    assert pod_name in result.stdout
    pods = k8s_client.list_namespaced_pod(namespace="default").items
    assert any(p.metadata.name == pod_name for p in pods)
