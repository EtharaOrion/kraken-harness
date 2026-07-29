def test_workflow_0240_pod_label_patch_delete(cli, k8s_client, kubectl_bin, tmp_path):
    mfile = tmp_path / "m.yaml"
    mfile.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: wf-lpp-0240\n  namespace: default\nspec:\n  containers: [{name: c, image: nginx}]\n')
    r_apply = cli("apply", "-f", str(mfile))
    assert r_apply.returncode == 0, r_apply.stderr
    r_label = cli("label", "pod", "wf-lpp-0240", "team=wf", "-n", "default")
    assert r_label.returncode == 0, r_label.stderr
    r_patch = cli("patch", "pod", "wf-lpp-0240", "-n", "default", "--type=merge", "-p", '{"metadata":{"annotations":{"note":"n240"}}}')
    assert r_patch.returncode == 0, r_patch.stderr
    r_get = cli("get", "pod", "wf-lpp-0240", "-n", "default", "-o", "yaml")
    assert r_get.returncode == 0, r_get.stderr
    r_del = cli("delete", "pod", "wf-lpp-0240", "-n", "default")
    assert r_del.returncode == 0, r_del.stderr
