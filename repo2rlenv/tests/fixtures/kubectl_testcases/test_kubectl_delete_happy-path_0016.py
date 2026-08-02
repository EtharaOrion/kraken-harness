def test_delete_job_0016_by_name(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: batch/v1\nkind: Job\nmetadata:\n  name: djo-0016\n  namespace: default\nspec:\n  template:\n    spec:\n      restartPolicy: Never\n      containers: [{name: c, image: busybox, command: [echo, hi]}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("delete", "job", "djo-0016", "-n", "default")
    assert result.returncode == 0, result.stderr
