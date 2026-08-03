def test_workflow_0063_ns_pod_lifecycle(cli, k8s_client, kubectl_bin, tmp_path):
    r_ns = cli("create", "namespace", "wf-ns-0063")
    assert r_ns.returncode == 0, r_ns.stderr
    manifest = tmp_path / "pod.yaml"
    manifest.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: wf-pod-0063\n  namespace: wf-ns-0063\nspec:\n  containers: [{name: c, image: nginx}]\n')
    r_apply = cli("apply", "-f", str(manifest))
    assert r_apply.returncode == 0, r_apply.stderr
    r_get = cli("get", "pod", "wf-pod-0063", "-n", "wf-ns-0063")
    assert r_get.returncode == 0, r_get.stderr
    r_desc = cli("describe", "pod", "wf-pod-0063", "-n", "wf-ns-0063")
    assert r_desc.returncode == 0, r_desc.stderr
    r_del = cli("delete", "namespace", "wf-ns-0063")
    assert r_del.returncode == 0, r_del.stderr
