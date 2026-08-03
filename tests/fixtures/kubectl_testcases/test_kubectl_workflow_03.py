from kubernetes import client


def test_workflow_apply_deployment_scale_get_delete(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "dep.yaml"
    manifest.write_text(
        "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: wf03-dep\n  namespace: default\n"
        "spec:\n  replicas: 1\n  selector:\n    matchLabels: {app: wf03}\n"
        "  template:\n    metadata:\n      labels: {app: wf03}\n"
        "    spec:\n      containers: [{name: c, image: nginx}]\n"
    )
    r_apply = cli("apply", "-f", str(manifest))
    assert r_apply.returncode == 0, r_apply.stderr
    r_scale = cli("scale", "deployment", "wf03-dep", "--replicas=3", "-n", "default")
    assert r_scale.returncode == 0, r_scale.stderr
    r_get = cli("get", "deployment", "wf03-dep", "-n", "default")
    assert r_get.returncode == 0, r_get.stderr
    assert "wf03-dep" in r_get.stdout
    read = client.AppsV1Api(k8s_client.api_client).read_namespaced_deployment(name="wf03-dep", namespace="default")
    assert read.spec.replicas == 3
    r_del = cli("delete", "deployment", "wf03-dep", "-n", "default")
    assert r_del.returncode == 0, r_del.stderr
