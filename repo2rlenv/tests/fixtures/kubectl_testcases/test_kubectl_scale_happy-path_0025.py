from kubernetes import client


def test_scale_statefulset_0025_to_7(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: StatefulSet\nmetadata:\n  name: ssta-0025\n  namespace: default\nspec:\n  replicas: 1\n  serviceName: ssta-0025-svc\n  selector: {matchLabels: {app: ssta-0025}}\n  template:\n    metadata:\n      labels: {app: ssta-0025}\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("scale", "statefulset", "ssta-0025", "--replicas=7", "-n", "default")
    assert result.returncode == 0, result.stderr
    read = client.AppsV1Api(k8s_client.api_client).read_namespaced_stateful_set(name="ssta-0025", namespace="default")
    assert read.spec.replicas == 7
