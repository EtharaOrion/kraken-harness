def test_delete_from_manifest_file_removes_resource(cli, k8s_client, kubectl_bin, tmp_path):
    pod_name = "pod-del-hp05"
    manifest = tmp_path / "pod.yaml"
    manifest.write_text(
        f"apiVersion: v1\nkind: Pod\nmetadata:\n  name: {pod_name}\n  namespace: default\n"
        "spec:\n  containers: [{name: c, image: nginx}]\n"
    )
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("delete", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert f"pod/{pod_name}" in result.stdout
    assert "deleted" in result.stdout.lower()
    pods = k8s_client.list_namespaced_pod(namespace="default").items
    assert not any(p.metadata.name == pod_name for p in pods)
