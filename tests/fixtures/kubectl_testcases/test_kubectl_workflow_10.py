def test_workflow_label_then_get_by_selector_then_unlabel(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "pod.yaml"
    manifest.write_text(
        "apiVersion: v1\nkind: Pod\nmetadata:\n  name: wf10-pod\n  namespace: default\n"
        "spec:\n  containers: [{name: c, image: nginx}]\n"
    )
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    r_lab = cli("label", "pod", "wf10-pod", "env=prod", "-n", "default")
    assert r_lab.returncode == 0, r_lab.stderr
    r_get_labeled = cli("get", "pods", "-l", "env=prod", "-n", "default")
    assert r_get_labeled.returncode == 0, r_get_labeled.stderr
    assert "wf10-pod" in r_get_labeled.stdout
    r_unlab = cli("label", "pod", "wf10-pod", "env-", "-n", "default")
    assert r_unlab.returncode == 0, r_unlab.stderr
    pod = next(p for p in k8s_client.list_namespaced_pod(namespace="default").items if p.metadata.name == "wf10-pod")
    labels = pod.metadata.labels or {}
    assert "env" not in labels
