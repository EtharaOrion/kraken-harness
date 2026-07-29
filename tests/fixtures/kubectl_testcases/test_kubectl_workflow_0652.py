def test_workflow_0652_apply_delete_by_file_configmap(cli, kubectl_bin, tmp_path):
    mfile = tmp_path / "m.yaml"
    mfile.write_text('apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: wf-df-co-0652\n  namespace: default\ndata:\n  k1: v1\n  k2: v2\n')
    r_apply = cli("apply", "-f", str(mfile))
    assert r_apply.returncode == 0, r_apply.stderr
    r_del = cli("delete", "-f", str(mfile))
    assert r_del.returncode == 0, r_del.stderr
