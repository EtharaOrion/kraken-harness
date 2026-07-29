from kubernetes import client


def test_scale_replicaset_0034_to_4(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: ReplicaSet\nmetadata:\n  name: srep-0034\n  namespace: default\nspec:\n  replicas: 1\n  selector: {matchLabels: {app: rs}}\n  template:\n    metadata:\n      labels: {app: rs}\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("scale", "replicaset", "srep-0034", "--replicas=4", "-n", "default")
    assert result.returncode == 0, result.stderr
    read = client.AppsV1Api(k8s_client.api_client).read_namespaced_replica_set(name="srep-0034", namespace="default")
    assert read.spec.replicas == 4
