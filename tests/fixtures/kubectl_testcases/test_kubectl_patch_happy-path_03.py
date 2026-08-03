from kubernetes import client


def test_patch_deployment_updates_replicas(cli, k8s_client, kubectl_bin, tmp_path):
    apps = client.AppsV1Api(k8s_client.api_client)
    ns = "default"
    dep_name = f"dep-pt-h03-{tmp_path.name.replace('_', '-').lower()[:32]}"
    body = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": dep_name, "namespace": ns},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": dep_name}},
            "template": {
                "metadata": {"labels": {"app": dep_name}},
                "spec": {"containers": [{"name": "c", "image": "nginx"}]},
            },
        },
    }
    apps.create_namespaced_deployment(namespace=ns, body=body)
    result = cli("patch", "deployment", dep_name, "-n", ns, "-p", '{"spec":{"replicas":3}}')
    assert result.returncode == 0, result.stderr
    assert "patched" in result.stdout.lower()
    dep = apps.read_namespaced_deployment(name=dep_name, namespace=ns)
    assert dep.spec.replicas == 3
