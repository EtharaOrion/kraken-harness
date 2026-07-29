def test_apply_cronjob_0038_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text("apiVersion: batch/v1\nkind: CronJob\nmetadata:\n  name: aicr-0038\n  namespace: default\nspec:\n  schedule: '*/5 * * * *'\n  jobTemplate:\n    spec:\n      template:\n        spec:\n          restartPolicy: Never\n          containers: [{name: c, image: busybox, command: [echo, hi]}]\n")
    r1 = cli("apply", "-f", str(manifest))
    assert r1.returncode == 0, r1.stderr
    r2 = cli("apply", "-f", str(manifest))
    assert r2.returncode == 0, r2.stderr
