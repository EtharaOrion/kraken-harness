def test_label_pod_0386_remove(cli, kubectl_bin, k8s_client, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: lr-0386\n  namespace: default\n  labels:\n    drop: "yes"\nspec:\n  containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "pod", "lr-0386", "drop-", "-n", "default")
    assert result.returncode == 0, result.stderr
    pod = next(p for p in k8s_client.list_namespaced_pod(namespace="default").items if p.metadata.name == "lr-0386")
    labels = pod.metadata.labels or {}
    assert "drop" not in labels
