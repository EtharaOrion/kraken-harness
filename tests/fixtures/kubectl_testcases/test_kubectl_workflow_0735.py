def test_workflow_0735_apply_delete_by_file_pod(cli, kubectl_bin, tmp_path):
    mfile = tmp_path / "m.yaml"
    mfile.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: wf-df-po-0735\n  namespace: default\nspec:\n  containers: [{name: c, image: nginx}]\n')
    r_apply = cli("apply", "-f", str(mfile))
    assert r_apply.returncode == 0, r_apply.stderr
    r_del = cli("delete", "-f", str(mfile))
    assert r_del.returncode == 0, r_del.stderr
