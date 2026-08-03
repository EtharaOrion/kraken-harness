def test_patch_pod_strategic_adds_label(cli, k8s_client, kubectl_bin, tmp_path):
    pod_name = f"pod-pt-h01-{tmp_path.name.replace('_', '-').lower()[:32]}"
    manifest = tmp_path / "pod.yaml"
    manifest.write_text(
        f"apiVersion: v1\nkind: Pod\nmetadata:\n  name: {pod_name}\n  namespace: default\n"
        "spec:\n  containers: [{name: c, image: nginx}]\n"
    )
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "pod", pod_name, "-n", "default", "-p", '{"metadata":{"labels":{"env":"prod"}}}')
    assert result.returncode == 0, result.stderr
    assert "patched" in result.stdout.lower()
    pod = k8s_client.read_namespaced_pod(name=pod_name, namespace="default")
    assert pod.metadata.labels is not None
    assert pod.metadata.labels.get("env") == "prod"
