from kubernetes import client


def test_scale_statefulset_0024_to_6(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: StatefulSet\nmetadata:\n  name: ssta-0024\n  namespace: default\nspec:\n  replicas: 1\n  serviceName: ssta-0024-svc\n  selector: {matchLabels: {app: ssta-0024}}\n  template:\n    metadata:\n      labels: {app: ssta-0024}\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("scale", "statefulset", "ssta-0024", "--replicas=6", "-n", "default")
    assert result.returncode == 0, result.stderr
    read = client.AppsV1Api(k8s_client.api_client).read_namespaced_stateful_set(name="ssta-0024", namespace="default")
    assert read.spec.replicas == 6
