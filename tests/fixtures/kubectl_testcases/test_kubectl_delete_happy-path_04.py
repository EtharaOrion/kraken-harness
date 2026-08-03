from kubernetes import client
from kubernetes.client.rest import ApiException


def test_delete_deployment_removes_resource(cli, k8s_client, kubectl_bin):
    kubectl_bin(["create", "namespace", "del-dep-hp04"])
    dep = client.V1Deployment(
        metadata=client.V1ObjectMeta(name="d-hp04", namespace="del-dep-hp04"),
        spec=client.V1DeploymentSpec(
            replicas=1,
            selector=client.V1LabelSelector(match_labels={"app": "d-hp04"}),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={"app": "d-hp04"}),
                spec=client.V1PodSpec(containers=[client.V1Container(name="c", image="nginx")]),
            ),
        ),
    )
    client.AppsV1Api(k8s_client.api_client).create_namespaced_deployment(namespace="del-dep-hp04", body=dep)
    result = cli("delete", "deployment", "d-hp04", "-n", "del-dep-hp04")
    assert result.returncode == 0, result.stderr
    assert "deployment.apps/d-hp04" in result.stdout
    assert "deleted" in result.stdout.lower()
    try:
        client.AppsV1Api(k8s_client.api_client).read_namespaced_deployment(name="d-hp04", namespace="del-dep-hp04")
        assert False, "deployment still exists"
    except ApiException as e:
        assert e.status == 404
