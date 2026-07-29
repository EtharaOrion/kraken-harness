def test_describe_pod_shows_details(cli, k8s_client, kubectl_bin, tmp_path):
    pod_name = f"pod-{tmp_path.name.replace('_', '-').lower()[:40]}"
    manifest = tmp_path / "pod.yaml"
    manifest.write_text(
        f"apiVersion: v1\nkind: Pod\nmetadata:\n  name: {pod_name}\n  namespace: default\n"
        "spec:\n  containers: [{name: c, image: nginx}]\n"
    )
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "pod", pod_name, "--namespace", "default")
    assert result.returncode == 0, result.stderr
    assert pod_name in result.stdout
    assert "Name:" in result.stdout
    assert "Namespace:" in result.stdout
    pods = k8s_client.list_namespaced_pod(namespace="default").items
    assert any(p.metadata.name == pod_name for p in pods)
