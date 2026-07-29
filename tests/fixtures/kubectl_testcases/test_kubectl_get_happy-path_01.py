def test_get_pod_by_name_returns_it(cli, k8s_client, kubectl_bin, tmp_path):
    pod_name = f"get-hp01-{tmp_path.name.replace('_', '-').lower()[:30]}"
    manifest = tmp_path / "pod.yaml"
    manifest.write_text(
        f"apiVersion: v1\nkind: Pod\nmetadata:\n  name: {pod_name}\n  namespace: default\n"
        "spec:\n  containers: [{name: c, image: nginx}]\n"
    )
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "pod", pod_name, "-n", "default")
    assert result.returncode == 0, result.stderr
    assert pod_name in result.stdout
    pods = k8s_client.list_namespaced_pod(namespace="default").items
    assert any(p.metadata.name == pod_name for p in pods)
