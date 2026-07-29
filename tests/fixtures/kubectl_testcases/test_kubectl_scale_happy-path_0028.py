from kubernetes import client


def test_scale_statefulset_0028_to_15(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: StatefulSet\nmetadata:\n  name: ssta-0028\n  namespace: default\nspec:\n  replicas: 1\n  serviceName: ssta-0028-svc\n  selector: {matchLabels: {app: ssta-0028}}\n  template:\n    metadata:\n      labels: {app: ssta-0028}\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("scale", "statefulset", "ssta-0028", "--replicas=15", "-n", "default")
    assert result.returncode == 0, result.stderr
    read = client.AppsV1Api(k8s_client.api_client).read_namespaced_stateful_set(name="ssta-0028", namespace="default")
    assert read.spec.replicas == 15
