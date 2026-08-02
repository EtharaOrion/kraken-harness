def test_workflow_apply_pod_patch_get_delete(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "pod.yaml"
    manifest.write_text(
        "apiVersion: v1\nkind: Pod\nmetadata:\n  name: wf05-pod\n  namespace: default\n"
        "spec:\n  containers: [{name: c, image: nginx}]\n"
    )
    r_apply = cli("apply", "-f", str(manifest))
    assert r_apply.returncode == 0, r_apply.stderr
    r_patch = cli(
        "patch", "pod", "wf05-pod", "-n", "default",
        "-p", '{"metadata":{"labels":{"stage":"patched"}}}',
    )
    assert r_patch.returncode == 0, r_patch.stderr
    r_get = cli("get", "pod", "wf05-pod", "-n", "default", "--show-labels")
    assert r_get.returncode == 0, r_get.stderr
    pod = next(p for p in k8s_client.list_namespaced_pod(namespace="default").items if p.metadata.name == "wf05-pod")
    assert pod.metadata.labels.get("stage") == "patched"
    r_del = cli("delete", "pod", "wf05-pod", "-n", "default")
    assert r_del.returncode == 0, r_del.stderr
