from kubernetes import client


def test_create_deployment_succeeds(cli, k8s_client, kubectl_bin, tmp_path):
    dep_name = f"dep-cr-hp04-{tmp_path.name.replace('_', '-').lower()[:30]}"
    result = cli("create", "deployment", dep_name, "--image=nginx", "-n", "default")
    assert result.returncode == 0, result.stderr
    apps = client.AppsV1Api(k8s_client.api_client)
    dep = apps.read_namespaced_deployment(name=dep_name, namespace="default")
    assert dep.metadata.name == dep_name
