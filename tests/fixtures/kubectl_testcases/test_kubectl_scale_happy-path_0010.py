from kubernetes import client


def test_scale_deployment_0010_to_4(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: sdep-0010\n  namespace: default\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      app: sdep-0010\n  template:\n    metadata:\n      labels:\n        app: sdep-0010\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("scale", "deployment", "sdep-0010", "--replicas=4", "-n", "default")
    assert result.returncode == 0, result.stderr
    read = client.AppsV1Api(k8s_client.api_client).read_namespaced_deployment(name="sdep-0010", namespace="default")
    assert read.spec.replicas == 4
