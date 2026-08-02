def test_get_job_0092_output_jsonpa(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: batch/v1\nkind: Job\nmetadata:\n  name: gfjo-0092\n  namespace: default\nspec:\n  template:\n    spec:\n      restartPolicy: Never\n      containers: [{name: c, image: busybox, command: [echo, hi]}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "job", "gfjo-0092", "-n", "default", "-o", "jsonpath={.metadata.name}")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
