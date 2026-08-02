def test_describe_job_0150_show_events(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: batch/v1\nkind: Job\nmetadata:\n  name: esjo-0150\n  namespace: default\nspec:\n  template:\n    spec:\n      restartPolicy: Never\n      containers: [{name: c, image: busybox, command: [echo, hi]}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "job", "esjo-0150", "-n", "default", "--show-events=true")
    assert result.returncode == 0, result.stderr
    assert "esjo-0150" in result.stdout
