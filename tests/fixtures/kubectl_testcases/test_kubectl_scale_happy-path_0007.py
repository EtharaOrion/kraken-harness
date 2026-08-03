from kubernetes import client


def test_scale_deployment_0007_to_1(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: sdep-0007\n  namespace: default\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      app: sdep-0007\n  template:\n    metadata:\n      labels:\n        app: sdep-0007\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("scale", "deployment", "sdep-0007", "--replicas=1", "-n", "default")
    assert result.returncode == 0, result.stderr
    read = client.AppsV1Api(k8s_client.api_client).read_namespaced_deployment(name="sdep-0007", namespace="default")
    assert read.spec.replicas == 1
