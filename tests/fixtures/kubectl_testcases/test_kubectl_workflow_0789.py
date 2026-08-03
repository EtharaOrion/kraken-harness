def test_workflow_0789_apply_delete_by_file_serviceaccount(cli, kubectl_bin, tmp_path):
    mfile = tmp_path / "m.yaml"
    mfile.write_text('apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: wf-df-se-0789\n  namespace: default\n')
    r_apply = cli("apply", "-f", str(mfile))
    assert r_apply.returncode == 0, r_apply.stderr
    r_del = cli("delete", "-f", str(mfile))
    assert r_del.returncode == 0, r_del.stderr
