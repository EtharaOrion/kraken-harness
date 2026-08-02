def test_label_existing_label_without_overwrite_returns_error(cli, k8s_client, kubectl_bin, tmp_path):
    pod_name = f"pod-lbl-ne03-{tmp_path.name.replace('_', '-').lower()[:30]}"
    manifest = tmp_path / "pod.yaml"
    manifest.write_text(
        f"apiVersion: v1\nkind: Pod\nmetadata:\n  name: {pod_name}\n  namespace: default\n"
        "  labels: {env: dev}\n"
        "spec:\n  containers: [{name: c, image: nginx}]\n"
    )
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "pod", pod_name, "-n", "default", "env=prod")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "already" in err or "exists" in err or "overwrite" in err
    pod = k8s_client.read_namespaced_pod(name=pod_name, namespace="default")
    assert pod.metadata.labels.get("env") == "dev"
