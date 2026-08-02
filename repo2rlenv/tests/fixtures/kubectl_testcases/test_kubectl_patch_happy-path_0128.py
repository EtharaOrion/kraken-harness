def test_patch_job_0128_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: batch/v1\nkind: Job\nmetadata:\n  name: pijo-0128\n  namespace: default\nspec:\n  template:\n    spec:\n      restartPolicy: Never\n      containers: [{name: c, image: busybox, command: [echo, hi]}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    r1 = cli("patch", "job", "pijo-0128", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x128"}}}')
    assert r1.returncode == 0, r1.stderr
    r2 = cli("patch", "job", "pijo-0128", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x128"}}}')
    assert r2.returncode == 0, r2.stderr
