def test_patch_cronjob_0040_merge(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text("apiVersion: batch/v1\nkind: CronJob\nmetadata:\n  name: pcr-0040\n  namespace: default\nspec:\n  schedule: '*/5 * * * *'\n  jobTemplate:\n    spec:\n      template:\n        spec:\n          restartPolicy: Never\n          containers: [{name: c, image: busybox, command: [echo, hi]}]\n")
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "cronjob", "pcr-0040", "-n", "default", "--type=merge", "-p", '{"metadata":{"labels":{"lane":"b40"}}}')
    assert result.returncode == 0, result.stderr
    assert "pcr-0040" in result.stdout
