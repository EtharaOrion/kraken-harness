def test_workflow_apply_patch_get_yaml_delete(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "pod.yaml"
    manifest.write_text(
        "apiVersion: v1\nkind: Pod\nmetadata:\n  name: wf11-pod\n  namespace: default\n"
        "spec:\n  containers: [{name: c, image: nginx}]\n"
    )
    r_apply = cli("apply", "-f", str(manifest))
    assert r_apply.returncode == 0, r_apply.stderr
    r_patch = cli(
        "patch", "pod", "wf11-pod", "-n", "default",
        "--type=merge",
        "-p", '{"metadata":{"annotations":{"team":"platform"}}}',
    )
    assert r_patch.returncode == 0, r_patch.stderr
    r_get = cli("get", "pod", "wf11-pod", "-n", "default", "-o", "yaml")
    assert r_get.returncode == 0, r_get.stderr
    assert "team: platform" in r_get.stdout
    r_del = cli("delete", "pod", "wf11-pod", "-n", "default")
    assert r_del.returncode == 0, r_del.stderr
    pods = k8s_client.list_namespaced_pod(namespace="default").items
    assert not any(p.metadata.name == "wf11-pod" for p in pods)
