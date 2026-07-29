def test_workflow_0628_apply_delete_by_file_secret(cli, kubectl_bin, tmp_path):
    mfile = tmp_path / "m.yaml"
    mfile.write_text('apiVersion: v1\nkind: Secret\nmetadata:\n  name: wf-df-se-0628\n  namespace: default\ntype: Opaque\nstringData:\n  token: s3cret\n')
    r_apply = cli("apply", "-f", str(mfile))
    assert r_apply.returncode == 0, r_apply.stderr
    r_del = cli("delete", "-f", str(mfile))
    assert r_del.returncode == 0, r_del.stderr
