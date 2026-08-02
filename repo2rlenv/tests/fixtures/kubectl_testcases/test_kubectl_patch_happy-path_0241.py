def test_patch_cronjob_0241_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text("apiVersion: batch/v1\nkind: CronJob\nmetadata:\n  name: picr-0241\n  namespace: default\nspec:\n  schedule: '*/5 * * * *'\n  jobTemplate:\n    spec:\n      template:\n        spec:\n          restartPolicy: Never\n          containers: [{name: c, image: busybox, command: [echo, hi]}]\n")
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    r1 = cli("patch", "cronjob", "picr-0241", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x241"}}}')
    assert r1.returncode == 0, r1.stderr
    r2 = cli("patch", "cronjob", "picr-0241", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x241"}}}')
    assert r2.returncode == 0, r2.stderr
