def test_workflow_0466_job_lifecycle(cli, kubectl_bin, tmp_path):
    mfile = tmp_path / "m.yaml"
    mfile.write_text('apiVersion: batch/v1\nkind: Job\nmetadata:\n  name: wf-job-0466\n  namespace: default\nspec:\n  template:\n    spec:\n      restartPolicy: Never\n      containers: [{name: c, image: busybox, command: [echo, hi]}]\n')
    r_apply = cli("apply", "-f", str(mfile))
    assert r_apply.returncode == 0, r_apply.stderr
    r_get = cli("get", "job", "wf-job-0466", "-n", "default")
    assert r_get.returncode == 0, r_get.stderr
    r_desc = cli("describe", "job", "wf-job-0466", "-n", "default")
    assert r_desc.returncode == 0, r_desc.stderr
    r_del = cli("delete", "job", "wf-job-0466", "-n", "default")
    assert r_del.returncode == 0, r_del.stderr
