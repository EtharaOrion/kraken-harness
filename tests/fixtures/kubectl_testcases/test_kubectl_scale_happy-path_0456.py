from kubernetes import client


def test_scale_deployment_0456_cycle(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: scy-0456\n  namespace: default\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      app: scy-0456\n  template:\n    metadata:\n      labels:\n        app: scy-0456\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    r1 = cli("scale", "deployment", "scy-0456", "--replicas=3", "-n", "default")
    assert r1.returncode == 0, r1.stderr
    up = client.AppsV1Api(k8s_client.api_client).read_namespaced_deployment(name="scy-0456", namespace="default")
    assert up.spec.replicas == 3
    r2 = cli("scale", "deployment", "scy-0456", "--replicas=1", "-n", "default")
    assert r2.returncode == 0, r2.stderr
    down = client.AppsV1Api(k8s_client.api_client).read_namespaced_deployment(name="scy-0456", namespace="default")
    assert down.spec.replicas == 1
