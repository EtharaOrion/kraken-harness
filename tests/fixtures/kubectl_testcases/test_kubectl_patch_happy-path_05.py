def test_patch_pod_idempotent_second_apply(cli, k8s_client, kubectl_bin, tmp_path):
    pod_name = f"pod-pt-h05-{tmp_path.name.replace('_', '-').lower()[:32]}"
    manifest = tmp_path / "pod.yaml"
    manifest.write_text(
        f"apiVersion: v1\nkind: Pod\nmetadata:\n  name: {pod_name}\n  namespace: default\n"
        "spec:\n  containers: [{name: c, image: nginx}]\n"
    )
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    first = cli("patch", "pod", pod_name, "-n", "default", "-p", '{"metadata":{"labels":{"tier":"backend"}}}')
    assert first.returncode == 0, first.stderr
    assert "patched" in first.stdout.lower()
    second = cli("patch", "pod", pod_name, "-n", "default", "-p", '{"metadata":{"labels":{"tier":"backend"}}}')
    assert second.returncode == 0, second.stderr
    out = second.stdout.lower()
    assert "no change" in out or "patched" in out
    pod = k8s_client.read_namespaced_pod(name=pod_name, namespace="default")
    assert pod.metadata.labels.get("tier") == "backend"
