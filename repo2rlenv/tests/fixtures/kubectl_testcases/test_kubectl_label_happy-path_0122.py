def test_label_cronjob_0122_add_team(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text("apiVersion: batch/v1\nkind: CronJob\nmetadata:\n  name: lcr-0122\n  namespace: default\nspec:\n  schedule: '*/5 * * * *'\n  jobTemplate:\n    spec:\n      template:\n        spec:\n          restartPolicy: Never\n          containers: [{name: c, image: busybox, command: [echo, hi]}]\n")
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "cronjob", "lcr-0122", "team=platform", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "lcr-0122" in result.stdout
