from kubernetes import client


def test_workflow_apply_deployment_scale_up_then_down_then_delete(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "dep.yaml"
    manifest.write_text(
        "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: wf07-dep\n  namespace: default\n"
        "spec:\n  replicas: 1\n  selector:\n    matchLabels: {app: wf07}\n"
        "  template:\n    metadata:\n      labels: {app: wf07}\n"
        "    spec:\n      containers: [{name: c, image: nginx}]\n"
    )
    r_apply = cli("apply", "-f", str(manifest))
    assert r_apply.returncode == 0, r_apply.stderr
    r_up = cli("scale", "deployment", "wf07-dep", "--replicas=5", "-n", "default")
    assert r_up.returncode == 0, r_up.stderr
    read_up = client.AppsV1Api(k8s_client.api_client).read_namespaced_deployment(name="wf07-dep", namespace="default")
    assert read_up.spec.replicas == 5
    r_down = cli("scale", "deployment", "wf07-dep", "--replicas=1", "-n", "default")
    assert r_down.returncode == 0, r_down.stderr
    read_down = client.AppsV1Api(k8s_client.api_client).read_namespaced_deployment(name="wf07-dep", namespace="default")
    assert read_down.spec.replicas == 1
    r_del = cli("delete", "deployment", "wf07-dep", "-n", "default")
    assert r_del.returncode == 0, r_del.stderr
