def test_patch_pod_merge_adds_annotation(cli, k8s_client, kubectl_bin, tmp_path):
    pod_name = f"pod-pt-h02-{tmp_path.name.replace('_', '-').lower()[:32]}"
    manifest = tmp_path / "pod.yaml"
    manifest.write_text(
        f"apiVersion: v1\nkind: Pod\nmetadata:\n  name: {pod_name}\n  namespace: default\n"
        "spec:\n  containers: [{name: c, image: nginx}]\n"
    )
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "pod", pod_name, "-n", "default", "--type=merge", "-p", '{"metadata":{"annotations":{"note":"hello"}}}')
    assert result.returncode == 0, result.stderr
    assert "patched" in result.stdout.lower()
    pod = k8s_client.read_namespaced_pod(name=pod_name, namespace="default")
    assert pod.metadata.annotations is not None
    assert pod.metadata.annotations.get("note") == "hello"
