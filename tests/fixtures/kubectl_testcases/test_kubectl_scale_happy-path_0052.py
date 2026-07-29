def test_scale_replicationcontroller_0052_to_15(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ReplicationController\nmetadata:\n  name: srrc-0052\n  namespace: default\nspec:\n  replicas: 1\n  selector: {app: rc}\n  template:\n    metadata:\n      labels: {app: rc}\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("scale", "replicationcontroller", "srrc-0052", "--replicas=15", "-n", "default")
    assert result.returncode == 0, result.stderr
