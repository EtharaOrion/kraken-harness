def test_patch_job_0036_strategic(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: batch/v1\nkind: Job\nmetadata:\n  name: pjo-0036\n  namespace: default\nspec:\n  template:\n    spec:\n      restartPolicy: Never\n      containers: [{name: c, image: busybox, command: [echo, hi]}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "job", "pjo-0036", "-n", "default", "-p", '{"metadata":{"labels":{"lane":"a36"}}}')
    assert result.returncode == 0, result.stderr
    assert "pjo-0036" in result.stdout
