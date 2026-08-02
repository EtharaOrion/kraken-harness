def test_apply_cronjob_0054_dryrun_client(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text("apiVersion: batch/v1\nkind: CronJob\nmetadata:\n  name: adcr-0054\n  namespace: default\nspec:\n  schedule: '*/5 * * * *'\n  jobTemplate:\n    spec:\n      template:\n        spec:\n          restartPolicy: Never\n          containers: [{name: c, image: busybox, command: [echo, hi]}]\n")
    result = cli("apply", "-f", str(manifest), "--dry-run=client")
    assert result.returncode == 0, result.stderr
    assert "adcr-0054" in result.stdout
